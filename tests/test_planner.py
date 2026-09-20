from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from random import Random

import pytest

from meal_planning_bot.models import (
    SLOT_MEAL_TYPE,
    SLOT_ORDER,
    MealType,
    PlannerSettings,
    ServedRecord,
    Slot,
)
from meal_planning_bot.planner import (
    NODE_CAP,
    NodeCapReached,
    PlannerFailure,
    Unsatisfiable,
    _candidate_ok,
    day_window,
    plan_week,
    redraw_slot,
    solve,
)
from tests.factories import DEFAULT_SETTINGS, catalogue, dish

WEEK_START = date(2026, 9, 14)


def test_planner_is_pure() -> None:
    source = Path("meal_planning_bot/planner.py").read_text()
    for forbidden in ("import sqlite3", "from telegram", "import telegram", "datetime.now"):
        assert forbidden not in source


def test_solve_fills_all_twenty_five_slots() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    plan = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(1))
    assert len(plan.entries) == 25
    assert {(e.day, e.slot) for e in plan.entries} == {(d, s) for d in range(5) for s in SLOT_ORDER}


def test_each_slot_draws_from_its_own_meal_type() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    by_id = {d.id: d for d in cat}
    plan = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(2))
    for entry in plan.entries:
        assert by_id[entry.dish_id].meal_type is SLOT_MEAL_TYPE[entry.slot]


def test_same_seed_same_plan() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    a = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(7))
    b = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(7))
    assert a.entries == b.entries


def test_different_seeds_different_plans() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    a = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(1))
    b = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(2))
    assert a.entries != b.entries


def test_daily_kcal_within_tolerance() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    by_id = {d.id: d for d in cat}
    plan = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(3))
    low, high = day_window(DEFAULT_SETTINGS)
    by_day: dict[int, int] = defaultdict(int)
    for entry in plan.entries:
        by_day[entry.day] += by_id[entry.dish_id].kcal
    for total in by_day.values():
        assert low <= total <= high


def test_no_dish_repeats_on_one_day() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    plan = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(4))
    by_day: dict[int, list[int]] = defaultdict(list)
    for entry in plan.entries:
        by_day[entry.day].append(entry.dish_id)
    for dishes in by_day.values():
        assert len(dishes) == len(set(dishes))


def test_food_repeat_limit_is_enforced() -> None:
    shared_food = 999
    settings = PlannerSettings(
        daily_kcal_target=1800,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=2,
        cooldown_days={t: 1 for t in MealType},
    )
    cat = [
        dish(1, MealType.BREAKFAST, 400, foods=[shared_food]),
        dish(2, MealType.SNACK, 200, foods=[shared_food]),
        dish(3, MealType.SNACK, 200, foods=[shared_food]),
        dish(4, MealType.SNACK, 200, foods=[123]),
        *[dish(10 + i, MealType.LUNCH, 600, foods=[200 + i]) for i in range(5)],
        *[dish(20 + i, MealType.DINNER, 400, foods=[300 + i]) for i in range(5)],
    ]
    plan = solve(cat, [], settings, WEEK_START, Random(5))
    by_id = {d.id: d for d in cat}
    for day in range(5):
        foods_today = Counter(
            food_id
            for entry in plan.entries
            if entry.day == day
            for food_id in (i.food_id for i in by_id[entry.dish_id].ingredients)
        )
        assert foods_today[shared_food] <= 2


def test_food_repeat_over_limit_is_unsatisfiable() -> None:
    shared_food = 999
    settings = PlannerSettings(
        daily_kcal_target=1800,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=1,
        cooldown_days={t: 1 for t in MealType},
    )
    cat = [
        dish(1, MealType.BREAKFAST, 400, foods=[shared_food]),
        dish(2, MealType.SNACK, 200, foods=[shared_food]),
        dish(3, MealType.SNACK, 200, foods=[shared_food]),
        *[dish(10 + i, MealType.LUNCH, 600, foods=[200 + i]) for i in range(5)],
        *[dish(20 + i, MealType.DINNER, 400, foods=[300 + i]) for i in range(5)],
    ]
    with pytest.raises(Unsatisfiable):
        solve(cat, [], settings, WEEK_START, Random(5))


def test_cooldown_blocks_a_dish_served_last_wednesday() -> None:
    # DEFAULT_SETTINGS has a 14-day lunch cooldown and 1-day cooldowns
    # elsewhere, so only the lunch pool needs to satisfy the constraint.
    cat = catalogue(6, {t: 400 for t in MealType})
    lunch_dishes = [d for d in cat if d.meal_type is MealType.LUNCH]
    served_last_wednesday = date(2026, 9, 9)
    history = [ServedRecord(dish_id=lunch_dishes[0].id, served_on=served_last_wednesday)]
    plan = solve(cat, history, DEFAULT_SETTINGS, WEEK_START, Random(6))
    used_ids = {e.dish_id for e in plan.entries}
    assert lunch_dishes[0].id not in used_ids


def test_friday_to_monday_gap_counts_as_three_days() -> None:
    friday = date(2026, 9, 11)
    monday = date(2026, 9, 14)
    assert (monday - friday).days == 3
    lunch = dish(1, MealType.LUNCH, 700)
    settings_allowed = PlannerSettings(
        daily_kcal_target=700,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=2,
        cooldown_days={
            MealType.BREAKFAST: 1,
            MealType.SNACK: 1,
            MealType.LUNCH: 3,
            MealType.DINNER: 1,
        },
    )
    settings_blocked = PlannerSettings(
        daily_kcal_target=700,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=2,
        cooldown_days={
            MealType.BREAKFAST: 1,
            MealType.SNACK: 1,
            MealType.LUNCH: 4,
            MealType.DINNER: 1,
        },
    )
    # A 3-day cooldown is satisfied by a gap of exactly 3; a 4-day one is not.
    assert _candidate_ok(lunch, monday, [], {}, [friday], settings_allowed)
    assert not _candidate_ok(lunch, monday, [], {}, [friday], settings_blocked)


def test_catalogue_needing_backtracking_is_solved() -> None:
    settings = PlannerSettings(
        daily_kcal_target=1800,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=1,
        cooldown_days={t: 1 for t in MealType},
    )
    # Both breakfast options share kcal, but only one avoids the food the
    # single lunch dish requires; a non-backtracking greedy fill fails
    # whenever it happens to lock in the wrong breakfast first.
    cat = [
        dish(1, MealType.BREAKFAST, 400, foods=[1]),
        dish(2, MealType.BREAKFAST, 400, foods=[2]),
        dish(3, MealType.SNACK, 200, foods=[3]),
        dish(4, MealType.SNACK, 200, foods=[4]),
        dish(5, MealType.LUNCH, 600, foods=[1]),
        dish(6, MealType.DINNER, 400, foods=[5]),
    ]
    for seed in range(10):
        plan = solve(cat, [], settings, WEEK_START, Random(seed))
        assert len(plan.entries) == 25


def test_node_cap_is_fifty_thousand() -> None:
    assert NODE_CAP == 50_000


def test_node_cap_ends_a_hopeless_search() -> None:
    import meal_planning_bot.planner as planner_module

    original_cap = planner_module.NODE_CAP
    planner_module.NODE_CAP = 20
    try:
        # Every breakfast and every snack dish shares one food, so breakfast
        # plus either snack slot always exceeds max_food_repeats_per_day —
        # no combination can ever succeed, but the kcal window is wide open,
        # so pruning never short-circuits the search before the cap does.
        cat = [
            *[dish(i, MealType.BREAKFAST, 400, foods=[1]) for i in range(1, 6)],
            *[dish(i, MealType.SNACK, 200, foods=[1]) for i in range(6, 11)],
            *[dish(i, MealType.LUNCH, 600, foods=[100 + i]) for i in range(11, 16)],
            *[dish(i, MealType.DINNER, 400, foods=[200 + i]) for i in range(16, 21)],
        ]
        settings = PlannerSettings(
            daily_kcal_target=1800,
            kcal_tolerance_pct=100,
            max_food_repeats_per_day=1,
            cooldown_days={t: 1 for t in MealType},
        )
        with pytest.raises(NodeCapReached):
            solve(cat, [], settings, WEEK_START, Random(1))
    finally:
        planner_module.NODE_CAP = original_cap


def test_redraw_slot_keeps_other_entries_and_honours_constraints() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    plan = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(9))
    new_plan = redraw_slot(plan, cat, [], DEFAULT_SETTINGS, WEEK_START, 2, Slot.LUNCH, Random(11))
    unchanged = [e for e in plan.entries if not (e.day == 2 and e.slot == Slot.LUNCH)]
    new_unchanged = [e for e in new_plan.entries if not (e.day == 2 and e.slot == Slot.LUNCH)]
    assert unchanged == new_unchanged
    by_id = {d.id: d for d in cat}
    redrawn = next(e for e in new_plan.entries if e.day == 2 and e.slot == Slot.LUNCH)
    assert by_id[redrawn.dish_id].meal_type is MealType.LUNCH
    day_dish_ids = [e.dish_id for e in new_plan.entries if e.day == 2]
    assert len(day_dish_ids) == len(set(day_dish_ids))


def test_redraw_slot_raises_when_nothing_fits() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    plan = solve(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(9))
    settings = PlannerSettings(
        daily_kcal_target=1,
        kcal_tolerance_pct=0,
        max_food_repeats_per_day=2,
        cooldown_days={t: 1 for t in MealType},
    )
    with pytest.raises(Unsatisfiable):
        redraw_slot(plan, cat, [], settings, WEEK_START, 2, Slot.LUNCH, Random(11))


def test_plan_week_succeeds_at_step_zero_when_unrelaxed() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    plan = plan_week(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(1))
    assert plan.relaxation == 0


def test_plan_week_reaches_step_one() -> None:
    # Exactly five lunch dishes for five days, so no reuse is needed within
    # the week itself; one of them was served 5 days before week_start, so
    # its gap to every day this week (5-9) clears the halved 7-day cooldown
    # on the later days but never clears the full 14-day one.
    lunch = [dish(100 + i, MealType.LUNCH, 700, foods=[]) for i in range(5)]
    breakfast = [dish(200, MealType.BREAKFAST, 400, foods=[])]
    snacks = [dish(300, MealType.SNACK, 200, foods=[]), dish(301, MealType.SNACK, 200, foods=[])]
    dinner = [dish(400, MealType.DINNER, 400, foods=[])]
    cat = [*lunch, *breakfast, *snacks, *dinner]
    settings = PlannerSettings(
        daily_kcal_target=1900,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=5,
        cooldown_days={
            MealType.BREAKFAST: 1,
            MealType.SNACK: 1,
            MealType.LUNCH: 14,
            MealType.DINNER: 1,
        },
    )
    history = [ServedRecord(dish_id=lunch[0].id, served_on=WEEK_START - timedelta(days=5))]
    plan = plan_week(cat, history, settings, WEEK_START, Random(1))
    assert plan.relaxation == 1


def test_plan_week_reaches_step_two() -> None:
    # Same shape as step 1, but the history gap (2 days, so 2-6 across the
    # week) is under both the full (14) and halved (7) cooldowns, only the
    # floor of 1 admits it.
    lunch = [dish(100 + i, MealType.LUNCH, 700, foods=[]) for i in range(5)]
    breakfast = [dish(200, MealType.BREAKFAST, 400, foods=[])]
    snacks = [dish(300, MealType.SNACK, 200, foods=[]), dish(301, MealType.SNACK, 200, foods=[])]
    dinner = [dish(400, MealType.DINNER, 400, foods=[])]
    cat = [*lunch, *breakfast, *snacks, *dinner]
    settings = PlannerSettings(
        daily_kcal_target=1900,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=5,
        cooldown_days={
            MealType.BREAKFAST: 1,
            MealType.SNACK: 1,
            MealType.LUNCH: 14,
            MealType.DINNER: 1,
        },
    )
    history = [ServedRecord(dish_id=lunch[0].id, served_on=WEEK_START - timedelta(days=2))]
    plan = plan_week(cat, history, settings, WEEK_START, Random(1))
    assert plan.relaxation == 2


def test_plan_week_reaches_step_three() -> None:
    # Breakfast and both snack dishes are forced to share one food every
    # day: three uses, which the default max_food_repeats_per_day of 2
    # cannot allow at any cooldown setting, only step 3's +1 can.
    shared_food = 999
    cat = [
        dish(1, MealType.BREAKFAST, 400, foods=[shared_food]),
        dish(2, MealType.SNACK, 200, foods=[shared_food]),
        dish(3, MealType.SNACK, 200, foods=[shared_food]),
        *[dish(10 + i, MealType.LUNCH, 600, foods=[200 + i]) for i in range(5)],
        *[dish(20 + i, MealType.DINNER, 400, foods=[300 + i]) for i in range(5)],
    ]
    settings = PlannerSettings(
        daily_kcal_target=1800,
        kcal_tolerance_pct=100,
        max_food_repeats_per_day=2,
        cooldown_days={t: 1 for t in MealType},
    )
    plan = plan_week(cat, [], settings, WEEK_START, Random(1))
    assert plan.relaxation == 3


def test_plan_week_reaches_step_four() -> None:
    # A single forced combination totals 2150 kcal: outside the 1900-2100
    # window of a 5% tolerance, inside the 1800-2200 window once doubled.
    cat = [
        dish(1, MealType.BREAKFAST, 400, foods=[]),
        dish(2, MealType.SNACK, 200, foods=[]),
        dish(3, MealType.SNACK, 200, foods=[]),
        dish(4, MealType.LUNCH, 850, foods=[]),
        dish(5, MealType.DINNER, 500, foods=[]),
    ]
    settings = PlannerSettings(
        daily_kcal_target=2000,
        kcal_tolerance_pct=5,
        max_food_repeats_per_day=2,
        cooldown_days={t: 1 for t in MealType},
    )
    plan = plan_week(cat, [], settings, WEEK_START, Random(1))
    assert plan.relaxation == 4


def test_never_relaxed_rules_hold_at_step_four() -> None:
    cat = [
        dish(1, MealType.BREAKFAST, 400, foods=[]),
        dish(2, MealType.SNACK, 200, foods=[]),
        dish(3, MealType.SNACK, 200, foods=[]),
        dish(4, MealType.LUNCH, 850, foods=[]),
        dish(5, MealType.DINNER, 500, foods=[]),
    ]
    settings = PlannerSettings(
        daily_kcal_target=2000,
        kcal_tolerance_pct=5,
        max_food_repeats_per_day=2,
        cooldown_days={t: 1 for t in MealType},
    )
    dish_by_id = {d.id: d for d in cat}
    plan = plan_week(cat, [], settings, WEEK_START, Random(1))
    assert plan.relaxation == 4
    by_day: dict[int, list[int]] = defaultdict(list)
    for e in plan.entries:
        by_day[e.day].append(e.dish_id)
        assert SLOT_MEAL_TYPE[e.slot] == dish_by_id[e.dish_id].meal_type
    for dishes in by_day.values():
        assert len(dishes) == len(set(dishes))


def test_failure_names_the_short_meal_type() -> None:
    cat = [
        d for d in catalogue(6, {t: 400 for t in MealType}) if d.meal_type is not MealType.DINNER
    ]
    with pytest.raises(PlannerFailure) as exc:
        plan_week(cat, [], DEFAULT_SETTINGS, WEEK_START, Random(1))
    assert "dinner" in str(exc.value)


def test_failure_states_kcal_window_reachability() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    settings = PlannerSettings(
        daily_kcal_target=1,
        kcal_tolerance_pct=0,
        max_food_repeats_per_day=2,
        cooldown_days={t: 1 for t in MealType},
    )
    with pytest.raises(PlannerFailure) as exc:
        plan_week(cat, [], settings, WEEK_START, Random(1))
    assert exc.value.diagnosis.kcal_window_reachable is False
