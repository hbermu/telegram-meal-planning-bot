"""Choosing by hand what a slot is: a dish from the catalogue, or a note for a
slot nobody is cooking. The chosen slot is pinned, so re-drawing the week keeps
it and draws the rest of the week around it."""

from dataclasses import dataclass
from datetime import date, timedelta

from meal_planning_bot import repo
from meal_planning_bot.formatting import (
    DAY_LABELS,
    DISH_FUZZY_PROMPT,
    DISH_NOT_FOUND_MESSAGE,
    NO_PLAN_MESSAGE,
    OVERRIDE_DAY_PROMPT,
    OVERRIDE_DEFAULT_NOTE,
    OVERRIDE_DISH_PROMPT,
    OVERRIDE_KEYWORD,
    OVERRIDE_NO_DISHES_MESSAGE,
    OVERRIDE_OUT_BUTTON,
    OVERRIDE_SLOT_PROMPT,
    OVERRIDE_USAGE_MESSAGE,
    OVERRIDE_WEEKEND_MESSAGE,
    PAGINATION_NEXT_BUTTON,
    PAGINATION_PREV_BUTTON,
    SLOT_LABELS,
    SLOT_NOT_PLANNED_MESSAGE,
    render_day,
    render_override_kcal_notice,
)
from meal_planning_bot.handlers import (
    ButtonRow,
    CallbackUpdateLike,
    ContextLike,
    Keyboard,
    UpdateLike,
    get_clock,
    get_conn,
    keyboards,
    load_dishes_for_plan,
)
from meal_planning_bot.handlers.plan import DAY_NAMES, SLOT_NAMES, fold
from meal_planning_bot.models import SLOT_MEAL_TYPE, SLOT_ORDER, Plan, PlanEntry, Slot
from meal_planning_bot.planner import apply_overrides, days_outside_window
from meal_planning_bot.weeks import NEXT_KEYWORD, ArgumentError, current_week_start, next_week_start

_TODAY_TOKEN = "hoy"
_TOMORROW_TOKEN = "manana"
# Enough dishes to choose from without a wall of buttons; the rest paginate.
_DISHES_PER_PAGE = 8


class WeekendError(Exception):
    pass


@dataclass(frozen=True)
class Choice:
    day: int
    slot: Slot
    is_next: bool
    dish_name: str
    note: str | None


def parse_override_args(args: list[str], today: date) -> Choice:
    tokens = list(args)
    is_next = False
    # The week keyword leads here, unlike in /swap: what follows the slot is
    # free text, so a trailing keyword could not be told from the text.
    if tokens and fold(tokens[0]) == NEXT_KEYWORD:
        is_next = True
        tokens = tokens[1:]
    if len(tokens) < 3:
        raise ArgumentError("override requires a day, a slot and what to eat")

    day_token, slot_token = fold(tokens[0]), fold(tokens[1])
    if day_token in (_TODAY_TOKEN, _TOMORROW_TOKEN):
        if is_next:
            raise ArgumentError("a relative day cannot address next week")
        named = today if day_token == _TODAY_TOKEN else today + timedelta(days=1)
        if named.weekday() >= 5:
            raise WeekendError
        day = named.weekday()
    elif day_token in DAY_NAMES:
        day = DAY_NAMES[day_token]
    else:
        raise ArgumentError(f"unknown day: {tokens[0]!r}")

    if slot_token not in SLOT_NAMES:
        raise ArgumentError(f"unknown slot: {tokens[1]!r}")

    rest = tokens[2:]
    if fold(rest[0]) == OVERRIDE_KEYWORD:
        note = " ".join(rest[1:]).strip() or OVERRIDE_DEFAULT_NOTE
        return Choice(day, SLOT_NAMES[slot_token], is_next, "", note)
    return Choice(day, SLOT_NAMES[slot_token], is_next, " ".join(rest).strip(), None)


def _back_to_plan(is_next: bool) -> Keyboard:
    return keyboards.back_to(f"menu:plan:{keyboards.week_token(is_next)}")


def _stored_plan(context: ContextLike, is_next: bool) -> Plan | None:
    today = get_clock(context)()
    week_start = next_week_start(today) if is_next else current_week_start(today)
    return repo.get_plan(get_conn(context), week_start)


async def _apply(
    update: UpdateLike, context: ContextLike, plan: Plan, entry: PlanEntry, is_next: bool
) -> None:
    conn = get_conn(context)
    updated = apply_overrides(plan, [entry])
    repo.save_plan(conn, updated)

    dishes = load_dishes_for_plan(conn, updated)
    settings = repo.planner_settings(conn)
    outside = [day for day in days_outside_window(updated, dishes, settings) if day == entry.day]
    text = render_day(updated, dishes, entry.day)
    notice = render_override_kcal_notice(outside)
    await update.reply_text(
        f"{text}\n\n{notice}" if notice else text, reply_markup=_back_to_plan(is_next)
    )


async def cmd_override(update: UpdateLike, context: ContextLike) -> None:
    today = get_clock(context)()
    try:
        choice = parse_override_args(list(context.args), today)
    except WeekendError:
        await update.reply_text(OVERRIDE_WEEKEND_MESSAGE)
        return
    except ArgumentError:
        await update.reply_text(OVERRIDE_USAGE_MESSAGE)
        return

    plan = _stored_plan(context, choice.is_next)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE)
        return
    if choice.slot not in {entry.slot for entry in plan.entries}:
        await update.reply_text(SLOT_NOT_PLANNED_MESSAGE)
        return

    if choice.note is not None:
        await _apply(
            update,
            context,
            plan,
            PlanEntry(
                day=choice.day, slot=choice.slot, dish_id=None, note=choice.note, override=True
            ),
            choice.is_next,
        )
        return

    matches = repo.find_dishes_by_name(get_conn(context), choice.dish_name)
    exact = next((d for d in matches if d.name.lower() == choice.dish_name.lower()), None)
    if exact is None and len(matches) == 1:
        exact = matches[0]
    if exact is not None:
        await _apply(
            update,
            context,
            plan,
            PlanEntry(day=choice.day, slot=choice.slot, dish_id=exact.id, override=True),
            choice.is_next,
        )
        return

    if not matches:
        # A name nobody recognises is a typo, not a decision to eat out: say so
        # rather than quietly turning it into a note.
        await update.reply_text(DISH_NOT_FOUND_MESSAGE)
        return

    week = keyboards.week_token(choice.is_next)
    row: ButtonRow = tuple(
        (d.name, f"ov:set:{week}:{choice.day}:{choice.slot.value}:{d.id}") for d in matches
    )
    await update.reply_text(DISH_FUZZY_PROMPT, reply_markup=(row,))


def _day_keyboard(is_next: bool) -> Keyboard:
    week = keyboards.week_token(is_next)
    rows = [
        tuple((DAY_LABELS[day], f"ov:slot:{week}:{day}") for day in days)
        for days in ((0, 1, 2), (3, 4))
    ]
    return (*rows, keyboards.back_row(f"menu:plan:{week}"))


def _slot_keyboard(is_next: bool, day: int, covered: set[Slot]) -> Keyboard:
    week = keyboards.week_token(is_next)
    buttons = [
        (SLOT_LABELS[slot], f"ov:pick:{week}:{day}:{slot.value}:1")
        for slot in SLOT_ORDER
        if slot in covered
    ]
    rows = [tuple(buttons[i : i + 2]) for i in range(0, len(buttons), 2)]
    return (*rows, keyboards.back_row(f"ov:day:{week}"))


def _pick_keyboard(
    is_next: bool, day: int, slot: Slot, page: int, dishes: list[tuple[int, str]]
) -> Keyboard:
    week = keyboards.week_token(is_next)
    start = (page - 1) * _DISHES_PER_PAGE
    rows: list[ButtonRow] = [
        ((name, f"ov:set:{week}:{day}:{slot.value}:{dish_id}"),)
        for dish_id, name in dishes[start : start + _DISHES_PER_PAGE]
    ]
    paging: list[tuple[str, str]] = []
    if page > 1:
        paging.append((PAGINATION_PREV_BUTTON, f"ov:pick:{week}:{day}:{slot.value}:{page - 1}"))
    if start + _DISHES_PER_PAGE < len(dishes):
        paging.append((PAGINATION_NEXT_BUTTON, f"ov:pick:{week}:{day}:{slot.value}:{page + 1}"))
    if paging:
        rows.append(tuple(paging))
    rows.append(((OVERRIDE_OUT_BUTTON, f"ov:out:{week}:{day}:{slot.value}"),))
    rows.append(keyboards.back_row(f"ov:slot:{week}:{day}"))
    return tuple(rows)


async def on_override_callback(update: CallbackUpdateLike, context: ContextLike) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    is_next = len(parts) > 2 and parts[2] == keyboards.NEXT

    plan = _stored_plan(context, is_next)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE, reply_markup=_back_to_plan(is_next))
        return

    if action == "day":
        await update.reply_text(OVERRIDE_DAY_PROMPT, reply_markup=_day_keyboard(is_next))
        return

    try:
        day = int(parts[3])
        slot = Slot(parts[4]) if action != "slot" else None
        page = int(parts[5]) if action == "pick" else 1
        dish_id = int(parts[5]) if action == "set" else None
    except (IndexError, ValueError):
        # A button from a retired keyboard: start the choice again rather than
        # going quiet. See `../command-surface/navigation.md`.
        await update.reply_text(OVERRIDE_DAY_PROMPT, reply_markup=_day_keyboard(is_next))
        return

    covered = {entry.slot for entry in plan.entries}
    if action == "slot":
        await update.reply_text(
            OVERRIDE_SLOT_PROMPT.format(day=DAY_LABELS[day]),
            reply_markup=_slot_keyboard(is_next, day, covered),
        )
        return

    assert slot is not None
    if slot not in covered:
        await update.reply_text(SLOT_NOT_PLANNED_MESSAGE, reply_markup=_back_to_plan(is_next))
        return

    if action == "pick":
        meal_type = SLOT_MEAL_TYPE[slot]
        dishes = [
            (d.id, d.name)
            for d in repo.list_dishes(get_conn(context), archived=False)
            if d.meal_type is meal_type
        ]
        prompt = OVERRIDE_DISH_PROMPT if dishes else OVERRIDE_NO_DISHES_MESSAGE
        await update.reply_text(
            prompt, reply_markup=_pick_keyboard(is_next, day, slot, page, dishes)
        )
        return

    if action == "out":
        entry = PlanEntry(
            day=day, slot=slot, dish_id=None, note=OVERRIDE_DEFAULT_NOTE, override=True
        )
    else:
        assert dish_id is not None
        entry = PlanEntry(day=day, slot=slot, dish_id=dish_id, override=True)
    await _apply(update, context, plan, entry, is_next)
