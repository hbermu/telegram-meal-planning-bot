from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
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


Position = tuple[int, Slot]


@dataclass(frozen=True)
class Pinned:
    """A position someone chose by hand. The planner does not judge it: it
    holds it, charges the day for it, and draws the rest around it."""

    entry: PlanEntry
    dish: Dish | None

    @property
    def kcal(self) -> int:
        # A slot nobody is cooking feeds the day whatever somebody typed for it,
        # and nothing the planner can count when nobody knew.
        if self.dish is not None:
            return self.dish.kcal
        return self.entry.kcal or 0


def pin(overrides: Sequence[PlanEntry], catalogue: Sequence[Dish]) -> dict[Position, Pinned]:
    by_id = {d.id: d for d in catalogue}
    return {
        (entry.day, entry.slot): Pinned(
            entry=entry,
            # An override can name a dish that has since been archived, and it
            # still stands: it is what the household decided to eat.
            dish=by_id.get(entry.dish_id) if entry.dish_id is not None else None,
        )
        for entry in overrides
    }


def _bounds(
    positions: Sequence[Position],
    pools: Mapping[Slot, Sequence[Dish]],
    fixed: Mapping[Position, Pinned],
) -> tuple[dict[Position, int], dict[Position, int]]:
    cheapest: dict[Position, int] = {}
    dearest: dict[Position, int] = {}
    for position in positions:
        held = fixed.get(position)
        if held is not None:
            cheapest[position] = dearest[position] = held.kcal
            continue
        pool = pools[position[1]]
        cheapest[position] = min(d.kcal for d in pool)
        dearest[position] = max(d.kcal for d in pool)
    return cheapest, dearest


def _prune(
    running: int,
    remaining: Sequence[Position],
    cheapest: Mapping[Position, int],
    dearest: Mapping[Position, int],
    low: int,
    high: int,
) -> bool:
    return (
        running + sum(cheapest[p] for p in remaining) > high
        or running + sum(dearest[p] for p in remaining) < low
    )


def _positions(slots: Sequence[Slot]) -> tuple[tuple[int, Slot], ...]:
    ordered = [s for s in SLOT_ORDER if s in slots]
    return tuple((day, slot) for day in range(5) for slot in ordered)


def covered_slots(plan: Plan) -> set[Slot]:
    """The slots the draw plans. A drawn slot holds an entry on every day; one
    a user pinned by hand on a slot the draw skips holds it only on that day."""
    days: dict[Slot, set[int]] = defaultdict(set)
    for entry in plan.entries:
        days[entry.slot].add(entry.day)
    return {slot for slot, held in days.items() if len(held) == 5}


def _ordered(entries: Iterable[PlanEntry]) -> tuple[PlanEntry, ...]:
    return tuple(sorted(entries, key=lambda e: (e.day, SLOT_ORDER.index(e.slot))))


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


@dataclass(frozen=True)
class Search:
    """Everything a draw needs that does not change while it runs."""

    positions: tuple[Position, ...]
    pools: Mapping[Slot, Sequence[Dish]]
    fixed: Mapping[Position, Pinned]
    cheapest: Mapping[Position, int]
    dearest: Mapping[Position, int]
    floors: Mapping[int, int]
    week_start: date
    settings: PlannerSettings
    high: int
    rng: Random


@dataclass
class DayState:
    """The part of a draw that is rebuilt for each day of the week."""

    assigned: list[Dish]
    food_counts: dict[int, int]
    running: int


def _fits_day(search: Search, day: int, remaining: Sequence[Position], running: int) -> bool:
    if remaining:
        return not _prune(
            running, remaining, search.cheapest, search.dearest, search.floors[day], search.high
        )
    return search.floors[day] <= running <= search.high


def _fill(
    search: Search,
    index: int,
    state: DayState,
    last_served: dict[int, date],
    chosen: list[PlanEntry | None],
    node_count: list[int],
) -> bool:
    if index == len(search.positions):
        return True

    day, slot = search.positions[index]
    day_date = search.week_start + timedelta(days=day)
    remaining_today = [p for p in search.positions[index + 1 :] if p[0] == day]

    # A new day starts a fresh per-day state; the previous day's state is
    # discarded rather than restored, since backtracking into an earlier
    # day re-enters through its own undo path, not through here.
    if slot is search.positions[0][1]:
        state = DayState(assigned=[], food_counts={}, running=0)

    held = search.fixed.get((day, slot))
    if held is not None:
        node_count[0] += 1
        if node_count[0] > NODE_CAP:
            raise NodeCapReached
        return _fill_pinned(
            search, index, state, last_served, chosen, node_count, held, day_date, remaining_today
        )

    candidates = list(search.pools[slot])
    search.rng.shuffle(candidates)

    for dish in candidates:
        node_count[0] += 1
        if node_count[0] > NODE_CAP:
            raise NodeCapReached

        previous_occurrence = last_served.get(dish.id)
        occurrences = [previous_occurrence] if previous_occurrence is not None else []
        if not _candidate_ok(
            dish, day_date, state.assigned, state.food_counts, occurrences, search.settings
        ):
            continue

        previous_running = state.running
        new_running = previous_running + dish.kcal
        if not _fits_day(search, day, remaining_today, new_running):
            continue

        _charge(state, dish, new_running)
        last_served[dish.id] = day_date
        chosen[index] = PlanEntry(day=day, slot=slot, dish_id=dish.id)

        if _fill(search, index + 1, state, last_served, chosen, node_count):
            return True

        _refund(state, dish, previous_running)
        if previous_occurrence is None:
            del last_served[dish.id]
        else:
            last_served[dish.id] = previous_occurrence
        chosen[index] = None

    return False


def _fill_pinned(
    search: Search,
    index: int,
    state: DayState,
    last_served: dict[int, date],
    chosen: list[PlanEntry | None],
    node_count: list[int],
    held: Pinned,
    day_date: date,
    remaining_today: Sequence[Position],
) -> bool:
    # A pinned position has no alternatives and no constraints to satisfy: it is
    # what somebody said they are eating. It still charges the day, so the rest
    # of the day is drawn around it, and failing here means the week cannot be
    # drawn with it held -- which `plan_week` answers by honouring it anyway.
    day = held.entry.day
    previous_running = state.running
    new_running = previous_running + held.kcal
    if not _fits_day(search, day, remaining_today, new_running):
        return False

    previous_occurrence = None
    if held.dish is not None:
        previous_occurrence = last_served.get(held.dish.id)
        _charge(state, held.dish, new_running)
        last_served[held.dish.id] = day_date
    else:
        state.running = new_running
    chosen[index] = held.entry

    if _fill(search, index + 1, state, last_served, chosen, node_count):
        return True

    if held.dish is not None:
        _refund(state, held.dish, previous_running)
        if previous_occurrence is None:
            del last_served[held.dish.id]
        else:
            last_served[held.dish.id] = previous_occurrence
    else:
        state.running = previous_running
    chosen[index] = None
    return False


def _charge(state: DayState, dish: Dish, running: int) -> None:
    state.assigned.append(dish)
    for food_id in _food_ids(dish):
        state.food_counts[food_id] = state.food_counts.get(food_id, 0) + 1
    state.running = running


def _refund(state: DayState, dish: Dish, running: int) -> None:
    state.assigned.pop()
    for food_id in _food_ids(dish):
        state.food_counts[food_id] -= 1
    state.running = running


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


def _day_floors(low: int, fixed: Mapping[Position, Pinned]) -> dict[int, int]:
    # A day with a slot nobody is cooking cannot reach the target either, for
    # the same reason a partial plan cannot: the floor goes, the ceiling stays.
    # A note somebody put calories on is not that case: the day is accounted
    # for, so it keeps its floor like any other.
    uncooked = {
        day for (day, _slot), held in fixed.items() if held.dish is None and held.entry.kcal is None
    }
    return {day: 0 if day in uncooked else low for day in range(5)}


def solve(
    catalogue: Sequence[Dish],
    history: Sequence[ServedRecord],
    settings: PlannerSettings,
    week_start: date,
    rng: Random,
    slots: Sequence[Slot],
    fixed: Mapping[Position, Pinned] | None = None,
) -> Plan:
    if not slots:
        raise Unsatisfiable("no slot has enough active dishes")

    held = fixed or {}
    pools = _pools_by_slot(catalogue, slots)
    positions = _positions(slots)
    for day, slot in positions:
        if not pools[slot] and (day, slot) not in held:
            raise Unsatisfiable(f"no active dishes for slot {slot.value}")

    low, high = day_window(settings)
    low = _floor(low, slots)
    cheapest, dearest = _bounds(positions, pools, held)
    search = Search(
        positions=positions,
        pools=pools,
        fixed=held,
        cheapest=cheapest,
        dearest=dearest,
        floors=_day_floors(low, held),
        week_start=week_start,
        settings=settings,
        high=high,
        rng=rng,
    )
    chosen: list[PlanEntry | None] = [None] * len(positions)

    solved = _fill(
        search,
        0,
        DayState(assigned=[], food_counts={}, running=0),
        _seed_last_served(history),
        chosen,
        [0],
    )
    if not solved:
        raise Unsatisfiable("no plan satisfies the constraints")

    entries = []
    for entry in chosen:
        assert entry is not None
        entries.append(entry)
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
    # A hand-picked entry there is released the way a pin always is, which on a
    # slot nobody draws leaves the slot empty.
    covered = covered_slots(plan)
    if slot not in covered:
        kept = [e for e in plan.entries if not (e.day == day and e.slot == slot)]
        if len(kept) == len(plan.entries):
            raise SlotNotPlanned(slot)
        return replace(plan, entries=tuple(kept))

    by_id = {d.id: d for d in catalogue}
    meal_type = SLOT_MEAL_TYPE[slot]
    pool = [d for d in catalogue if d.active and d.meal_type is meal_type]
    if not pool:
        raise Unsatisfiable(f"no active dishes for slot {slot.value}")

    other_entries = [e for e in plan.entries if not (e.day == day and e.slot == slot)]
    day_date = week_start + timedelta(days=day)
    low, high = day_window(settings)
    low = _floor(low, covered)
    if any(e.day == day and e.dish_id is None for e in other_entries):
        low = 0

    assigned_today = [
        by_id[e.dish_id]
        for e in other_entries
        if e.day == day and e.dish_id is not None and e.dish_id in by_id
    ]
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
        new_entries = _ordered((*other_entries, PlanEntry(day=day, slot=slot, dish_id=dish.id)))
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


def apply_overrides(plan: Plan, overrides: Sequence[PlanEntry]) -> Plan:
    """Lay the hand-picked entries over a plan that was drawn without them: in
    place of the drawn entry where there is one, and added to the day on a slot
    the draw does not cover. Also the last resort when no relaxation step can
    hold them: an override is a decision, not a request, so it is never dropped
    for being inconvenient."""
    held = {(entry.day, entry.slot): entry for entry in overrides}
    drawn = {(entry.day, entry.slot) for entry in plan.entries}
    entries = [held.get((entry.day, entry.slot), entry) for entry in plan.entries]
    entries.extend(entry for position, entry in held.items() if position not in drawn)
    return replace(plan, entries=_ordered(entries))


def days_outside_window(
    plan: Plan, dishes: Mapping[int, Dish], settings: PlannerSettings
) -> tuple[int, ...]:
    """The days whose calories no longer land inside the window. A hand-picked
    slot can push a day out of it, and the bot says so rather than refusing."""
    low, high = day_window(settings)
    low = _floor(low, covered_slots(plan))
    outside = []
    for day in range(5):
        today = [e for e in plan.entries if e.day == day]
        if not today:
            continue
        # A note nobody put calories on takes the floor away with it, exactly
        # as it does for the draw; one that carries them counts like a dish.
        floor = 0 if any(e.dish_id is None and e.kcal is None for e in today) else low
        total = sum(
            dishes[e.dish_id].kcal if e.dish_id is not None else (e.kcal or 0)
            for e in today
            if e.dish_id is None or e.dish_id in dishes
        )
        if not (floor <= total <= high):
            outside.append(day)
    return tuple(outside)


def plan_week(
    catalogue: Sequence[Dish],
    history: Sequence[ServedRecord],
    settings: PlannerSettings,
    week_start: date,
    rng: Random,
    allow_partial: bool,
    overrides: Sequence[PlanEntry] = (),
) -> Plan:
    slots = eligible_slots(catalogue) if allow_partial else SLOT_ORDER
    # An override on a slot this draw does not cover is no part of the search:
    # it is laid on its day afterwards, so the draw neither charges the day for
    # it nor drops it.
    held = [entry for entry in overrides if entry.slot in slots]
    beside = [entry for entry in overrides if entry.slot not in slots]
    fixed = pin(held, catalogue)
    for step, attempt in enumerate(_ladder(settings)):
        try:
            plan = solve(catalogue, history, attempt, week_start, rng, slots, fixed)
        except (Unsatisfiable, NodeCapReached):
            continue
        return apply_overrides(replace(plan, relaxation=step), beside)

    if held:
        # No step could draw a week around the hand-picked slots. They still
        # stand: draw the week without them and lay them back on top. The day
        # they sit in may then miss its calorie window, which the bot reports
        # rather than treating as a reason to refuse.
        return apply_overrides(
            plan_week(catalogue, history, settings, week_start, rng, allow_partial), overrides
        )

    raise PlannerFailure(_diagnose(catalogue, settings, slots))
