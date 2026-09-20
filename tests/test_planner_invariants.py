from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from functools import cache
from itertools import product
from random import Random

import pytest

from meal_planning_bot.models import (
    SLOT_MEAL_TYPE,
    SLOT_ORDER,
    Dish,
    MealType,
    Plan,
    PlannerSettings,
    ServedRecord,
)
from meal_planning_bot.planner import PlannerFailure, _ladder, day_window, plan_week
from tests.factories import DEFAULT_SETTINGS, dish
from tests.fixtures.realistic_catalogue import REALISTIC_CATALOGUE


def assert_plan_valid(
    plan: Plan,
    catalogue: Sequence[Dish],
    history: Sequence[ServedRecord],
    settings: PlannerSettings,
    week_start: date,
) -> None:
    effective = _ladder(settings)[plan.relaxation]
    by_id = {d.id: d for d in catalogue}
    low, high = day_window(effective)

    assert len(plan.entries) == 25
    assert {(e.day, e.slot) for e in plan.entries} == {(d, s) for d in range(5) for s in SLOT_ORDER}

    last_served = {r.dish_id: r.served_on for r in history}
    by_day: dict[int, list[Dish]] = defaultdict(list)
    for entry in sorted(plan.entries, key=lambda e: (e.day, SLOT_ORDER.index(e.slot))):
        dish_obj = by_id[entry.dish_id]
        assert dish_obj.meal_type is SLOT_MEAL_TYPE[entry.slot]
        by_day[entry.day].append(dish_obj)

    for day, dishes in by_day.items():
        day_date = week_start + timedelta(days=day)

        ids = [d.id for d in dishes]
        assert len(ids) == len(set(ids)), f"day {day} repeats a dish"

        foods = Counter(i.food_id for d in dishes for i in d.ingredients)
        worst = max(foods.values(), default=0)
        assert worst <= effective.max_food_repeats_per_day, f"day {day} food repeat {worst}"

        total = sum(d.kcal for d in dishes)
        assert low <= total <= high, f"day {day} kcal {total} outside [{low}, {high}]"

        for dish_obj in dishes:
            previous = last_served.get(dish_obj.id)
            if previous is not None:
                gap = (day_date - previous).days
                assert gap >= effective.cooldown_days[dish_obj.meal_type], (
                    f"dish {dish_obj.id} repeated after {gap} days"
                )
            last_served[dish_obj.id] = day_date


def _generate_catalogue(rng: Random) -> list[Dish]:
    # Deliberately mean. An earlier version of this generator produced catalogues so
    # comfortable that all 200 seeds solved at relaxation 0 with no history, which made
    # the fuzz green while exercising neither the cooldown, the food-repeat limit, the
    # kcal window, nor a single rung of the relaxation ladder.
    per_type = {
        MealType.BREAKFAST: rng.randint(3, 8),
        MealType.SNACK: rng.randint(6, 14),
        MealType.LUNCH: rng.randint(3, 10),
        MealType.DINNER: rng.randint(3, 10),
    }
    food_pool = list(range(1, rng.randint(4, 12)))
    # One case in twenty is scaled right out of the calorie window, so the sweep covers
    # genuine failure and not only the five rungs of success.
    scale = 0.5 if rng.random() < 0.05 else 1.0
    base_kcal = {
        MealType.BREAKFAST: round(400 * scale),
        MealType.SNACK: round(180 * scale),
        MealType.LUNCH: round(700 * scale),
        MealType.DINNER: round(540 * scale),
    }
    dishes: list[Dish] = []
    next_id = 1
    for meal_type, count in per_type.items():
        for _ in range(count):
            dishes.append(
                dish(
                    next_id,
                    meal_type,
                    kcal=base_kcal[meal_type] + rng.randint(-200, 200),
                    foods=rng.sample(food_pool, k=min(len(food_pool), rng.randint(1, 3))),
                )
            )
            next_id += 1
    return dishes


WEEK_START = date(2026, 9, 14)
FUZZ_SEEDS = 200
TINY_SEEDS = 30


def _generate_history(catalogue: Sequence[Dish], rng: Random) -> list[ServedRecord]:
    # Without history every cooldown is vacuous and the ladder is unreachable.
    served = rng.sample(list(catalogue), k=rng.randint(0, len(catalogue) // 2))
    return [
        ServedRecord(dish_id=d.id, served_on=WEEK_START - timedelta(days=rng.randint(1, 20)))
        for d in served
    ]


def _fuzz_case(seed: int) -> tuple[list[Dish], list[ServedRecord]]:
    rng = Random(seed)
    catalogue = _generate_catalogue(rng)
    return catalogue, _generate_history(catalogue, rng)


@cache
def _fuzz_outcome(seed: int) -> tuple[list[Dish], list[ServedRecord], Plan | None]:
    # Cached because the per-seed test below and the coverage sweep further down need the
    # same 200 results; solving each catalogue twice put the sweep over its time budget.
    catalogue, history = _fuzz_case(seed)
    try:
        plan = plan_week(catalogue, history, DEFAULT_SETTINGS, WEEK_START, Random(seed))
    except PlannerFailure:
        return catalogue, history, None
    return catalogue, history, plan


@pytest.mark.parametrize("seed", range(FUZZ_SEEDS))
def test_every_returned_plan_is_valid(seed: int) -> None:
    catalogue, history, plan = _fuzz_outcome(seed)
    if plan is None:
        return
    assert_plan_valid(plan, catalogue, history, DEFAULT_SETTINGS, WEEK_START)


def test_the_fuzz_actually_exercises_the_solver() -> None:
    """A fuzz suite that always succeeds, or always fails, asserts nothing.

    This test measures the sweep instead of trusting it. Without it the generator can be
    softened -- or the ladder broken -- and the 200 cases above stay green while covering
    one code path.
    """
    outcomes: Counter[int | None] = Counter()
    for seed in range(FUZZ_SEEDS):
        _, _, plan = _fuzz_outcome(seed)
        outcomes[plan.relaxation if plan is not None else None] += 1

    solved = sum(v for k, v in outcomes.items() if k is not None)
    relaxed = sum(v for k, v in outcomes.items() if k is not None and k > 0)

    assert solved >= FUZZ_SEEDS // 4, f"almost everything failed; generator too mean: {outcomes}"
    assert outcomes[None] >= 1, f"nothing ever failed; generator too generous: {outcomes}"
    assert relaxed >= 1, f"the relaxation ladder is never reached: {outcomes}"


def _tiny_catalogue(rng: Random) -> list[Dish]:
    # Small enough that brute force terminates, and mean enough that a real share of the
    # seeds are genuinely unsatisfiable -- otherwise test_failures_are_genuine below never
    # runs its brute force and passes by never entering its own body.
    # The scale is the failure lever. Too few dishes does not make a week unsatisfiable --
    # at the loosest rung a single lunch may legally repeat every day -- but a catalogue
    # whose whole day lands far outside the calorie window cannot be solved at any rung.
    scale = rng.choice([0.4, 0.7, 1.0, 1.0, 1.4, 2.2])
    dishes: list[Dish] = []
    next_id = 1
    for meal_type in MealType:
        count = rng.randint(2, 4) if meal_type is MealType.SNACK else rng.randint(1, 3)
        for _ in range(count):
            base = round(
                {
                    MealType.BREAKFAST: 400,
                    MealType.SNACK: 180,
                    MealType.LUNCH: 700,
                    MealType.DINNER: 540,
                }[meal_type]
                * scale
            )
            dishes.append(
                dish(
                    next_id,
                    meal_type,
                    kcal=base + rng.randint(-250, 250),
                    foods=rng.sample(range(1, 4), k=rng.randint(1, 2)),
                )
            )
            next_id += 1
    return dishes


def _day_kcal_ok(dishes: Sequence[Dish], settings: PlannerSettings) -> bool:
    low, high = day_window(settings)
    total = sum(d.kcal for d in dishes)
    return low <= total <= high


def _day_food_ok(dishes: Sequence[Dish], settings: PlannerSettings) -> bool:
    foods = Counter(i.food_id for d in dishes for i in d.ingredients)
    return max(foods.values(), default=0) <= settings.max_food_repeats_per_day


def brute_force_exists(
    catalogue: Sequence[Dish], settings: PlannerSettings, week_start: date
) -> bool:
    pools = {s: [d for d in catalogue if d.meal_type is SLOT_MEAL_TYPE[s]] for s in SLOT_ORDER}
    if any(not pools[s] for s in SLOT_ORDER):
        return False

    def day_solutions() -> list[tuple[Dish, ...]]:
        solutions = []
        for combo in product(*(pools[s] for s in SLOT_ORDER)):
            ids = [d.id for d in combo]
            if len(ids) != len(set(ids)):
                continue
            if not _day_food_ok(combo, settings):
                continue
            if not _day_kcal_ok(combo, settings):
                continue
            solutions.append(combo)
        return solutions

    solutions = day_solutions()
    if not solutions:
        return False

    last_served: dict[int, date] = {}

    def backtrack(day: int, last_served: dict[int, date]) -> bool:
        if day == 5:
            return True
        day_date = week_start + timedelta(days=day)
        for combo in solutions:
            ok = True
            for dish_obj in combo:
                previous = last_served.get(dish_obj.id)
                if previous is not None:
                    gap = (day_date - previous).days
                    if gap < settings.cooldown_days[dish_obj.meal_type]:
                        ok = False
                        break
            if not ok:
                continue
            updated = dict(last_served)
            for dish_obj in combo:
                updated[dish_obj.id] = day_date
            if backtrack(day + 1, updated):
                return True
        return False

    return backtrack(0, last_served)


def test_the_soundness_sweep_has_genuine_failures() -> None:
    """Guards the test below, which is a no-op on any seed that happens to succeed."""
    failures = 0
    for seed in range(TINY_SEEDS):
        try:
            plan_week(_tiny_catalogue(Random(seed)), [], DEFAULT_SETTINGS, WEEK_START, Random(seed))
        except PlannerFailure:
            failures += 1
    assert failures >= TINY_SEEDS // 4, (
        f"only {failures}/{TINY_SEEDS} tiny catalogues fail, so the brute-force check below "
        "almost never runs"
    )


@pytest.mark.parametrize("seed", range(TINY_SEEDS))
def test_failures_are_genuine(seed: int) -> None:
    rng = Random(seed)
    catalogue = _tiny_catalogue(rng)
    try:
        plan_week(catalogue, [], DEFAULT_SETTINGS, WEEK_START, Random(seed))
    except PlannerFailure:
        loosest = _ladder(DEFAULT_SETTINGS)[-1]
        assert not brute_force_exists(catalogue, loosest, WEEK_START)


def test_fifty_weeks_never_need_relaxation() -> None:
    catalogue = REALISTIC_CATALOGUE
    weeks = 50
    history: list[ServedRecord] = []
    week_start = date(2026, 1, 5)
    served: Counter[int] = Counter()

    for week in range(weeks):
        plan = plan_week(catalogue, history, DEFAULT_SETTINGS, week_start, Random(week))
        assert plan.relaxation == 0, f"week {week} needed relaxation {plan.relaxation}"
        assert_plan_valid(plan, catalogue, history, DEFAULT_SETTINGS, week_start)
        for entry in plan.entries:
            history.append(ServedRecord(entry.dish_id, week_start + timedelta(days=entry.day)))
            served[entry.dish_id] += 1
        history = [r for r in history if (week_start - r.served_on).days <= 60]
        week_start += timedelta(days=7)

    # Structural bound: a 14-day lunch cooldown over `weeks * 7` days caps
    # how often any single lunch dish can legally recur.
    total_days = weeks * 7
    lunch_cap = total_days // DEFAULT_SETTINGS.cooldown_days[MealType.LUNCH] + 1
    lunch_ids = {d.id for d in catalogue if d.meal_type is MealType.LUNCH}
    for dish_id in lunch_ids:
        assert served[dish_id] <= lunch_cap, f"dish {dish_id} served {served[dish_id]} times"

    for dish_obj in catalogue:
        assert served[dish_obj.id] > 0, f"dish {dish_obj.id} was never served over {weeks} weeks"
