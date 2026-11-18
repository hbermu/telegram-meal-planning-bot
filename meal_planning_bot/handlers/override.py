"""Choosing by hand what a slot is: a dish from the catalogue, or a note typed
for something the catalogue does not have. The chosen slot is pinned, so
re-drawing the week keeps it and draws the rest of the week around it."""

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from meal_planning_bot import repo
from meal_planning_bot.formatting import (
    DAY_LABELS,
    DISH_FUZZY_PROMPT,
    DISH_NOT_FOUND_MESSAGE,
    NO_PLAN_MESSAGE,
    OVERRIDE_CUSTOM_BUTTON,
    OVERRIDE_DAY_PROMPT,
    OVERRIDE_DEFAULT_NOTE,
    OVERRIDE_DISH_PROMPT,
    OVERRIDE_KEYWORD,
    OVERRIDE_SLOT_PROMPT,
    OVERRIDE_USAGE_MESSAGE,
    OVERRIDE_WEEKEND_MESSAGE,
    PAGINATION_NEXT_BUTTON,
    PAGINATION_PREV_BUTTON,
    SLOT_LABELS,
    TODAY_BUTTON,
    render_day,
    render_override_custom_prompt,
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
_DISH_COLUMNS = 2
_DISH_ROWS = 6
_DISHES_PER_PAGE = _DISH_COLUMNS * _DISH_ROWS
_ACTIONS = ("slot", "pick", "set", "custom")
# Where the slot waiting for a typed dish is kept. A wizard started after the
# prompt clears it, so its answers never land in the plan by mistake.
PENDING_NOTE_KEY = "override_note"


class OverrideContextLike(ContextLike, Protocol):
    user_data: MutableMapping[str, object]


class WeekendError(Exception):
    pass


@dataclass(frozen=True)
class PendingNote:
    chat_id: int
    is_next: bool
    day: int
    slot: Slot


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


async def cmd_override(update: UpdateLike, context: OverrideContextLike) -> None:
    today = get_clock(context)()
    if not context.args:
        context.user_data.pop(PENDING_NOTE_KEY, None)
        if _stored_plan(context, False) is None:
            await update.reply_text(NO_PLAN_MESSAGE)
            return
        await update.reply_text(OVERRIDE_DAY_PROMPT, reply_markup=_day_keyboard(False, today))
        return

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


def _day_keyboard(is_next: bool, today: date) -> Keyboard:
    week = keyboards.week_token(is_next)
    rows = [
        tuple((DAY_LABELS[day], f"ov:slot:{week}:{day}") for day in days)
        for days in ((0, 1, 2), (3, 4))
    ]
    if not is_next and today.weekday() < 5:
        rows.insert(0, ((TODAY_BUTTON, f"ov:slot:{week}:{today.weekday()}"),))
    return (*rows, keyboards.back_row(f"menu:plan:{week}"))


def _slot_keyboard(is_next: bool, day: int) -> Keyboard:
    week = keyboards.week_token(is_next)
    buttons = [(SLOT_LABELS[slot], f"ov:pick:{week}:{day}:{slot.value}:1") for slot in SLOT_ORDER]
    rows = [tuple(buttons[i : i + 2]) for i in range(0, len(buttons), 2)]
    return (*rows, keyboards.back_row(f"ov:day:{week}"))


def _pick_keyboard(
    is_next: bool, day: int, slot: Slot, page: int, dishes: list[tuple[int, str]]
) -> Keyboard:
    target = f"{keyboards.week_token(is_next)}:{day}:{slot.value}"
    buttons = [
        (OVERRIDE_CUSTOM_BUTTON, f"ov:custom:{target}"),
        *((name, f"ov:set:{target}:{dish_id}") for dish_id, name in dishes),
    ]
    last_page = (len(buttons) - 1) // _DISHES_PER_PAGE + 1
    # A button from before the catalogue shrank can point past the last page.
    page = min(page, last_page)
    start = (page - 1) * _DISHES_PER_PAGE
    shown = buttons[start : start + _DISHES_PER_PAGE]
    rows: list[ButtonRow] = [
        tuple(shown[i : i + _DISH_COLUMNS]) for i in range(0, len(shown), _DISH_COLUMNS)
    ]
    paging: list[tuple[str, str]] = []
    if page > 1:
        paging.append((PAGINATION_PREV_BUTTON, f"ov:pick:{target}:{page - 1}"))
    if page < last_page:
        paging.append((PAGINATION_NEXT_BUTTON, f"ov:pick:{target}:{page + 1}"))
    if paging:
        rows.append(tuple(paging))
    rows.append(keyboards.back_row(f"ov:slot:{keyboards.week_token(is_next)}:{day}"))
    return tuple(rows)


async def on_override_callback(update: CallbackUpdateLike, context: OverrideContextLike) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    # Any tap moves on from a custom-dish prompt, the back button included.
    context.user_data.pop(PENDING_NOTE_KEY, None)

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    is_next = len(parts) > 2 and parts[2] == keyboards.NEXT
    today = get_clock(context)()

    plan = _stored_plan(context, is_next)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE, reply_markup=_back_to_plan(is_next))
        return

    try:
        if action not in _ACTIONS:
            raise ValueError(action)
        day = int(parts[3])
        if not 0 <= day < len(DAY_LABELS):
            raise ValueError(day)
        slot = Slot(parts[4]) if action != "slot" else None
        page = max(int(parts[5]), 1) if action == "pick" else 1
        dish_id = int(parts[5]) if action == "set" else None
    except (IndexError, ValueError):
        # The day prompt itself, or a button from a retired keyboard: start the
        # choice again rather than going quiet. See
        # `../command-surface/navigation.md`.
        await update.reply_text(OVERRIDE_DAY_PROMPT, reply_markup=_day_keyboard(is_next, today))
        return

    if action == "slot":
        await update.reply_text(
            OVERRIDE_SLOT_PROMPT.format(day=DAY_LABELS[day]),
            reply_markup=_slot_keyboard(is_next, day),
        )
        return

    assert slot is not None

    if action == "pick":
        meal_type = SLOT_MEAL_TYPE[slot]
        dishes = [
            (d.id, d.name)
            for d in repo.list_dishes(get_conn(context), archived=False)
            if d.meal_type is meal_type
        ]
        await update.reply_text(
            OVERRIDE_DISH_PROMPT, reply_markup=_pick_keyboard(is_next, day, slot, page, dishes)
        )
        return

    if action == "custom":
        chat = update.effective_chat
        assert chat is not None
        context.user_data[PENDING_NOTE_KEY] = PendingNote(chat.id, is_next, day, slot)
        await update.reply_text(
            render_override_custom_prompt(day, slot),
            reply_markup=keyboards.back_to(
                f"ov:pick:{keyboards.week_token(is_next)}:{day}:{slot.value}:1"
            ),
        )
        return

    assert dish_id is not None
    entry = PlanEntry(day=day, slot=slot, dish_id=dish_id, override=True)
    await _apply(update, context, plan, entry, is_next)


async def on_override_text(update: UpdateLike, context: OverrideContextLike, text: str) -> bool:
    """Pin the dish typed after the custom-dish prompt. Answers whether the text
    was that dish, so a message nobody asked for here can go to a wizard."""
    pending = context.user_data.get(PENDING_NOTE_KEY)
    chat = update.effective_chat
    if not isinstance(pending, PendingNote) or chat is None or chat.id != pending.chat_id:
        return False
    del context.user_data[PENDING_NOTE_KEY]

    plan = _stored_plan(context, pending.is_next)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE, reply_markup=_back_to_plan(pending.is_next))
        return True
    entry = PlanEntry(
        day=pending.day, slot=pending.slot, dish_id=None, note=text.strip(), override=True
    )
    await _apply(update, context, plan, entry, pending.is_next)
    return True
