from meal_planning_bot import repo
from meal_planning_bot.access import private_only
from meal_planning_bot.formatting import (
    SET_USAGE_MESSAGE,
    render_setting_bad_time,
    render_setting_changed,
    render_setting_out_of_range,
    render_settings,
    render_unknown_setting_key,
)
from meal_planning_bot.handlers import ContextLike, UpdateLike, get_conn
from meal_planning_bot.repo import SETTING_SPECS, IntSpec, SettingError

_RESCHEDULE_KEYS = frozenset({"weekly_post_weekday", "weekly_post_time", "daily_post_time"})


async def cmd_settings(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    rows = repo.all_settings(conn)
    await update.reply_text(render_settings(rows))


async def _cmd_set(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    if len(context.args) < 2:
        await update.reply_text(SET_USAGE_MESSAGE)
        return

    key = context.args[0]
    raw_value = " ".join(context.args[1:])

    if key not in SETTING_SPECS:
        await update.reply_text(render_unknown_setting_key(sorted(SETTING_SPECS)))
        return

    spec = SETTING_SPECS[key]
    try:
        old_value, new_value = repo.set_setting(conn, key, raw_value)
    except SettingError:
        if isinstance(spec, IntSpec):
            await update.reply_text(render_setting_out_of_range(key, spec.low, spec.high))
        else:
            await update.reply_text(render_setting_bad_time(key))
        return

    await update.reply_text(render_setting_changed(key, old_value, new_value))

    if key in _RESCHEDULE_KEYS:
        reschedule = context.bot_data.get("reschedule")
        if reschedule is not None:
            assert callable(reschedule)
            reschedule(key)


cmd_set = private_only(_cmd_set)
