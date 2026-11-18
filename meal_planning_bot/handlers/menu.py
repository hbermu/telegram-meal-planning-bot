from meal_planning_bot import repo
from meal_planning_bot.formatting import (
    CATALOGUE_MENU_HEADER,
    MAIN_MENU_HEADER,
    REGENERATE_CONFIRM_PROMPT,
    SETTINGS_MENU_HINT,
    render_help,
    render_settings,
)
from meal_planning_bot.handlers import (
    CallbackUpdateLike,
    ContextLike,
    UpdateLike,
    get_clock,
    get_conn,
    keyboards,
)
from meal_planning_bot.handlers.plan import cmd_today, post_shopping, regenerate, show_plan
from meal_planning_bot.weeks import current_week_start, next_week_start


async def show_main(update: UpdateLike, context: ContextLike) -> None:
    await update.reply_text(MAIN_MENU_HEADER, reply_markup=keyboards.main_menu())


async def _show_week(
    update: CallbackUpdateLike, context: ContextLike, action: str, is_next: bool
) -> None:
    today = get_clock(context)()
    week_start = next_week_start(today) if is_next else current_week_start(today)
    if action == "plan":
        await show_plan(update, context, week_start, is_next)
    elif action == "shopping":
        await post_shopping(update, context, week_start, is_next)
    elif action == "regen":
        await update.reply_text(
            REGENERATE_CONFIRM_PROMPT, reply_markup=keyboards.regenerate_confirm(is_next)
        )
    else:
        await regenerate(update, context, week_start, is_next)


async def on_menu_callback(update: CallbackUpdateLike, context: ContextLike) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action in ("plan", "shopping", "regen", "regenyes"):
        await _show_week(update, context, action, len(parts) > 2 and parts[2] == keyboards.NEXT)
        return

    if action == "today":
        await cmd_today(update, context)
        return

    if action == "catalog":
        await update.reply_text(CATALOGUE_MENU_HEADER, reply_markup=keyboards.catalogue_menu())
        return

    if action == "settings":
        rows = repo.all_settings(get_conn(context))
        await update.reply_text(
            f"{render_settings(rows)}\n\n{SETTINGS_MENU_HINT}",
            reply_markup=keyboards.back_to(keyboards.MAIN),
        )
        return

    if action == "help":
        await update.reply_text(render_help(), reply_markup=keyboards.back_to(keyboards.MAIN))
        return

    # An inline keyboard outlives the message it was sent on, so a tap can
    # arrive carrying a button this version no longer knows. The main menu is
    # the honest answer: it always exists and it leads everywhere.
    await show_main(update, context)
