import unicodedata
from collections.abc import Sequence

from meal_planning_bot import repo
from meal_planning_bot.formatting import (
    NO_PLAN_MESSAGE,
    SWAP_USAGE_MESSAGE,
    UNKNOWN_ARGUMENT_MESSAGE,
    WEEKEND_MESSAGE,
    render_day,
    render_plan,
    render_planner_failure,
    render_relaxation_notice,
    render_shopping,
    render_swap_unsatisfiable,
)
from meal_planning_bot.handlers import (
    ContextLike,
    UpdateLike,
    get_clock,
    get_conn,
    get_rng,
    load_all_foods,
    load_dishes_for_plan,
)
from meal_planning_bot.models import Slot
from meal_planning_bot.planner import PlannerFailure, Unsatisfiable, plan_week, redraw_slot
from meal_planning_bot.shopping import aggregate
from meal_planning_bot.weeks import (
    NEXT_KEYWORD,
    ArgumentError,
    current_week_start,
    next_week_start,
    resolve_week,
)

_DAY_NAMES: dict[str, int] = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 4,
}

_SLOT_NAMES: dict[str, Slot] = {
    "desayuno": Slot.BREAKFAST,
    "snack1": Slot.SNACK1,
    "comida": Slot.LUNCH,
    "snack2": Slot.SNACK2,
    "cena": Slot.DINNER,
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def parse_swap_args(args: Sequence[str]) -> tuple[int, Slot, bool]:
    tokens = list(args)
    is_next = False
    if tokens and _fold(tokens[-1]) == NEXT_KEYWORD:
        is_next = True
        tokens = tokens[:-1]
    if len(tokens) != 2:
        raise ArgumentError("swap requires exactly a day and a slot")

    day_token, slot_token = _fold(tokens[0]), _fold(tokens[1])
    if day_token not in _DAY_NAMES:
        raise ArgumentError(f"unknown day: {tokens[0]!r}")
    if slot_token not in _SLOT_NAMES:
        raise ArgumentError(f"unknown slot: {tokens[1]!r}")
    return _DAY_NAMES[day_token], _SLOT_NAMES[slot_token], is_next


async def cmd_plan(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    today = get_clock(context)()
    try:
        week_start, is_next = resolve_week(context.args, today)
    except ArgumentError:
        await update.reply_text(UNKNOWN_ARGUMENT_MESSAGE)
        return

    plan = repo.get_plan(conn, week_start)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE)
        return

    dishes = load_dishes_for_plan(conn, plan)
    await update.reply_text(render_plan(plan, dishes, is_next_week=is_next))


async def cmd_today(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    today = get_clock(context)()
    if today.weekday() >= 5:
        await update.reply_text(WEEKEND_MESSAGE)
        return

    week_start = current_week_start(today)
    plan = repo.get_plan(conn, week_start)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE)
        return

    dishes = load_dishes_for_plan(conn, plan)
    await update.reply_text(render_day(plan, dishes, today.weekday()))


async def cmd_shopping(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    today = get_clock(context)()
    try:
        week_start, _is_next = resolve_week(context.args, today)
    except ArgumentError:
        await update.reply_text(UNKNOWN_ARGUMENT_MESSAGE)
        return

    plan = repo.get_plan(conn, week_start)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE)
        return

    dishes = load_dishes_for_plan(conn, plan)
    foods = load_all_foods(conn)
    for message in render_shopping(aggregate(plan, dishes, foods)):
        await update.reply_text(message)


async def cmd_regenerate(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    today = get_clock(context)()
    try:
        week_start, is_next = resolve_week(context.args, today)
    except ArgumentError:
        await update.reply_text(UNKNOWN_ARGUMENT_MESSAGE)
        return

    catalogue = repo.list_dishes(conn, archived=False)
    history = repo.scheduled_history(conn, today)
    settings = repo.planner_settings(conn)
    try:
        plan = plan_week(catalogue, history, settings, week_start, get_rng(context))
    except PlannerFailure as exc:
        await update.reply_text(render_planner_failure(exc.diagnosis))
        return

    repo.save_plan(conn, plan)
    dishes = load_dishes_for_plan(conn, plan)
    text = render_plan(plan, dishes, is_next_week=is_next)
    notice = render_relaxation_notice(plan.relaxation)
    await update.reply_text(f"{text}\n\n{notice}" if notice else text)


async def cmd_swap(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    today = get_clock(context)()
    try:
        day, slot, is_next = parse_swap_args(context.args)
    except ArgumentError:
        await update.reply_text(SWAP_USAGE_MESSAGE)
        return

    week_start = next_week_start(today) if is_next else current_week_start(today)
    plan = repo.get_plan(conn, week_start)
    if plan is None:
        await update.reply_text(NO_PLAN_MESSAGE)
        return

    catalogue = repo.list_dishes(conn, archived=False)
    history = repo.scheduled_history(conn, today)
    settings = repo.planner_settings(conn)
    try:
        new_plan = redraw_slot(
            plan, catalogue, history, settings, week_start, day, slot, get_rng(context)
        )
    except Unsatisfiable:
        await update.reply_text(render_swap_unsatisfiable())
        return

    repo.save_plan(conn, new_plan)
    dishes = load_dishes_for_plan(conn, new_plan)
    await update.reply_text(render_day(new_plan, dishes, day))
