from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from random import Random

from meal_planning_bot.models import (
    SLOT_MEAL_TYPE,
    SLOT_ORDER,
    Dish,
    MealType,
    Plan,
    PlanEntry,
    PlannerSettings,
    ServedRecord,
    Slot,
)

NODE_CAP = 50_000

MIN_ACTIVE_DISHES: dict[MealType, int] = {
    MealType.BREAKFAST: 5,
    MealType.SNACK: 10,
    MealType.LUNCH: 5,
    MealType.DINNER: 5,
}


class Unsatisfiable(Exception):
    pass


class NodeCapReached(Exception):
    pass


class SlotNotPlanned(Exception):
    def __init__(self, slot: Slot) -> None:
        self.slot = slot
        super().__init__(f"slot {slot.value} is not part of this plan")


@dataclass(frozen=True)
class MealTypeShortfall:
    meal_type: MealType
    active: int
    required: int


@dataclass(frozen=True)
class Diagnosis:
    shortfalls: tuple[MealTypeShortfall, ...]
    kcal_window_reachable: bool


def _format_diagnosis(diagnosis: Diagnosis) -> str:
    parts = [
        f"{s.meal_type.value} has {s.active} active dish(es), needs {s.required}"
        for s in diagnosis.shortfalls
    ]
    parts.append(f"kcal window reachable: {diagnosis.kcal_window_reachable}")
    return "; ".join(parts)


class PlannerFailure(Exception):
    def __init__(self, diagnosis: Diagnosis) -> None:
        self.diagnosis = diagnosis
        super().__init__(_format_diagnosis(diagnosis))


def day_window(settings: PlannerSettings) -> tuple[int, int]:
    slack = settings.daily_kcal_target * settings.kcal_tolerance_pct // 100
    return settings.daily_kcal_target - slack, settings.daily_kcal_target + slack


def _food_ids(dish: Dish) -> set[int]:
    return {ingredient.food_id for ingredient in dish.ingredients}


def _candidate_ok(
    dish: Dish,
    day_date: date,
    assigned_today: Sequence[Dish],
    food_counts_today: Mapping[int, int],
    other_occurrences: Sequence[date],
    settings: PlannerSettings,
) -> bool:
    if any(d.id == dish.id for d in assigned_today):
        return False
    for food_id in _food_ids(dish):
        if food_counts_today.get(food_id, 0) + 1 > settings.max_food_repeats_per_day:
            return False
    cooldown = settings.cooldown_days[dish.meal_type]
    return all(abs((day_date - occurrence).days) >= cooldown for occurrence in other_occurrences)


def _prune(
    running: int,
    remaining: Sequence[Slot],
    pools: Mapping[Slot, Sequence[Dish]],
    low: int,
    high: int,
) -> bool:
    cheapest = sum(min(d.kcal for d in pools[s]) for s in remaining)
    dearest = sum(max(d.kcal for d in pools[s]) for s in remaining)
    return running + cheapest > high or running + dearest < low


def _positions(slots: Sequence[Slot]) -> tuple[tuple[int, Slot], ...]:
    ordered = [s for s in SLOT_ORDER if s in slots]
    return tuple((day, slot) for day in range(5) for slot in ordered)


def eligible_slots(catalogue: Sequence[Dish]) -> tuple[Slot, ...]:
    active: dict[MealType, int] = defaultdict(int)
    for dish in catalogue:
        if dish.active:
            active[dish.meal_type] += 1
    return tuple(
        slot
        for slot in SLOT_ORDER
        if active[SLOT_MEAL_TYPE[slot]] >= MIN_ACTIVE_DISHES[SLOT_MEAL_TYPE[slot]]
    )


def _seed_last_served(history: Sequence[ServedRecord]) -> dict[int, date]:
    last_served: dict[int, date] = {}
    for record in history:
        current = last_served.get(record.dish_id)
        if current is None or record.served_on > current:
            last_served[record.dish_id] = record.served_on
    return last_served


def _fill(
    index: int,
    positions: Sequence[tuple[int, Slot]],
    pools: Mapping[Slot, Sequence[Dish]],
    week_start: date,
    settings: PlannerSettings,
    low: int,
    high: int,
    rng: Random,
    assigned_today: list[Dish],
    food_counts_today: dict[int, int],
    running: int,
    last_served: dict[int, date],
    chosen: list[int | None],
    node_count: list[int],
) -> bool:
    if index == len(positions):
        return True

    day, slot = positions[index]
    day_date = week_start + timedelta(days=day)
    remaining_today = [s for d, s in positions[index + 1 :] if d == day]

    # A new day starts a fresh per-day state; the previous day's state is
    # discarded rather than restored, since backtracking into an earlier
    # day re-enters through its own undo path, not through here.
    if slot is positions[0][1]:
        assigned_today = []
        food_counts_today = {}
        running = 0

    candidates = list(pools[slot])
    rng.shuffle(candidates)

    for dish in candidates:
        node_count[0] += 1
        if node_count[0] > NODE_CAP:
            raise NodeCapReached

        previous_occurrence = last_served.get(dish.id)
        occurrences = [previous_occurrence] if previous_occurrence is not None else []
        if not _candidate_ok(
            dish, day_date, assigned_today, food_counts_today, occurrences, settings
        ):
            continue

        new_running = running + dish.kcal
        if remaining_today:
            if _prune(new_running, remaining_today, pools, low, high):
                continue
        elif not (low <= new_running <= high):
            continue

        assigned_today.append(dish)
        for food_id in _food_ids(dish):
            food_counts_today[food_id] = food_counts_today.get(food_id, 0) + 1
        last_served[dish.id] = day_date
        chosen[index] = dish.id

        if _fill(
            index + 1,
            positions,
            pools,
            week_start,
            settings,
            low,
            high,
            rng,
            assigned_today,
            food_counts_today,
            new_running,
            last_served,
            chosen,
            node_count,
        ):
            return True

        assigned_today.pop()
        for food_id in _food_ids(dish):
            food_counts_today[food_id] -= 1
        if previous_occurrence is None:
            del last_served[dish.id]
        else:
            last_served[dish.id] = previous_occurrence
        chosen[index] = None

    return False


def _pools_by_slot(catalogue: Sequence[Dish], slots: Sequence[Slot]) -> dict[Slot, list[Dish]]:
    return {
        slot: [d for d in catalogue if d.active and d.meal_type is SLOT_MEAL_TYPE[slot]]
        for slot in slots
    }


# A plan that does not cover every slot of the day cannot reach the daily calorie
# target -- one lunch is not 2000 kcal -- so the lower bound is dropped and only
# the ceiling is enforced. Expressed as a floor of zero rather than as a mode flag,
# so every comparison downstream keeps its shape.
def _floor(low: int, slots: Collection[Slot]) -> int:
    return low if len(slots) == len(SLOT_ORDER) else 0


def solve(
    catalogue: Sequence[Dish],
    history: Sequence[ServedRecord],
    settings: PlannerSettings,
    week_start: date,
    rng: Random,
    slots: Sequence[Slot],
) -> Plan:
    if not slots:
        raise Unsatisfiable("no slot has enough active dishes")

    pools = _pools_by_slot(catalogue, slots)
    for slot in slots:
        if not pools[slot]:
            raise Unsatisfiable(f"no active dishes for slot {slot.value}")

    low, high = day_window(settings)
    low = _floor(low, slots)
    positions = _positions(slots)
    last_served = _seed_last_served(history)
    chosen: list[int | None] = [None] * len(positions)

    solved = _fill(
        0,
        positions,
        pools,
        week_start,
        settings,
        low,
        high,
        rng,
        [],
        {},
        0,
        last_served,
        chosen,
        [0],
    )
    if not solved:
        raise Unsatisfiable("no plan satisfies the constraints")

    entries = []
    for index, (day, slot) in enumerate(positions):
        dish_id = chosen[index]
        assert dish_id is not None
        entries.append(PlanEntry(day=day, slot=slot, dish_id=dish_id))
    return Plan(week_start=week_start, entries=tuple(entries))


def _occurrences_for(
    dish_id: int,
    history: Sequence[ServedRecord],
    other_entries: Sequence[PlanEntry],
    week_start: date,
) -> list[date]:
    dates = [r.served_on for r in history if r.dish_id == dish_id]
    dates.extend(week_start + timedelta(days=e.day) for e in other_entries if e.dish_id == dish_id)
    return dates


def redraw_slot(
    plan: Plan,
    catalogue: Sequence[Dish],
    history: Sequence[ServedRecord],
    settings: PlannerSettings,
    week_start: date,
    day: int,
    slot: Slot,
    rng: Random,
) -> Plan:
    # The plan itself records which slots it covers, so a partial plan needs no
    # extra argument here: a slot it never drew cannot be re-drawn in isolation.
    covered = {entry.slot for entry in plan.entries}
    if slot not in covered:
        raise SlotNotPlanned(slot)

    by_id = {d.id: d for d in catalogue}
    meal_type = SLOT_MEAL_TYPE[slot]
    pool = [d for d in catalogue if d.active and d.meal_type is meal_type]
    if not pool:
        raise Unsatisfiable(f"no active dishes for slot {slot.value}")

    other_entries = [e for e in plan.entries if not (e.day == day and e.slot == slot)]
    day_date = week_start + timedelta(days=day)
    low, high = day_window(settings)
    low = _floor(low, covered)

    assigned_today = [by_id[e.dish_id] for e in other_entries if e.day == day]
    food_counts_today: dict[int, int] = defaultdict(int)
    for dish in assigned_today:
        for food_id in _food_ids(dish):
            food_counts_today[food_id] += 1
    running_today = sum(d.kcal for d in assigned_today)

    candidates = list(pool)
    rng.shuffle(candidates)
    for dish in candidates:
        occurrences = _occurrences_for(dish.id, history, other_entries, week_start)
        if not _candidate_ok(
            dish, day_date, assigned_today, food_counts_today, occurrences, settings
        ):
            continue
        total = running_today + dish.kcal
        if not (low <= total <= high):
            continue
        new_entries = tuple(
            sorted(
                (*other_entries, PlanEntry(day=day, slot=slot, dish_id=dish.id)),
                key=lambda e: (e.day, SLOT_ORDER.index(e.slot)),
            )
        )
        return replace(plan, entries=new_entries)

    raise Unsatisfiable(f"no candidate fits day {day} slot {slot.value}")


def _ladder(base: PlannerSettings) -> list[PlannerSettings]:
    halved = {meal_type: max(1, n // 2) for meal_type, n in base.cooldown_days.items()}
    ones = dict.fromkeys(base.cooldown_days, 1)
    return [
        base,
        replace(base, cooldown_days=halved),
        replace(base, cooldown_days=ones),
        replace(
            base, cooldown_days=ones, max_food_repeats_per_day=base.max_food_repeats_per_day + 1
        ),
        replace(
            base,
            cooldown_days=ones,
            max_food_repeats_per_day=base.max_food_repeats_per_day + 1,
            kcal_tolerance_pct=base.kcal_tolerance_pct * 2,
        ),
    ]


def _diagnose(
    catalogue: Sequence[Dish], settings: PlannerSettings, slots: Sequence[Slot]
) -> Diagnosis:
    active_by_type: dict[MealType, list[Dish]] = defaultdict(list)
    for d in catalogue:
        if d.active:
            active_by_type[d.meal_type].append(d)

    shortfalls = tuple(
        MealTypeShortfall(meal_type, len(active_by_type[meal_type]), required)
        for meal_type, required in MIN_ACTIVE_DISHES.items()
        if len(active_by_type[meal_type]) < required
    )

    pools: dict[Slot, list[Dish]] = {slot: active_by_type[SLOT_MEAL_TYPE[slot]] for slot in slots}
    low, high = day_window(settings)
    low = _floor(low, slots)
    if not slots or any(not pools[slot] for slot in slots):
        reachable = False
    else:
        cheapest = sum(min(d.kcal for d in pools[slot]) for slot in slots)
        dearest = sum(max(d.kcal for d in pools[slot]) for slot in slots)
        reachable = cheapest <= high and dearest >= low

    return Diagnosis(shortfalls, reachable)


def plan_week(
    catalogue: Sequence[Dish],
    history: Sequence[ServedRecord],
    settings: PlannerSettings,
    week_start: date,
    rng: Random,
    allow_partial: bool,
) -> Plan:
    slots = eligible_slots(catalogue) if allow_partial else SLOT_ORDER
    for step, attempt in enumerate(_ladder(settings)):
        try:
            plan = solve(catalogue, history, attempt, week_start, rng, slots)
        except (Unsatisfiable, NodeCapReached):
            continue
        return replace(plan, relaxation=step)
    raise PlannerFailure(_diagnose(catalogue, settings, slots))
