import logging
import os
import sys
from collections.abc import Callable
from datetime import date
from random import Random
from sqlite3 import Connection
from typing import Any, cast

from telegram import (
    BotCommand,
)
from telegram.ext import (
    Application as PTBApplication,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ExtBot,
    MessageHandler,
    filters,
)

from meal_planning_bot import scheduler
from meal_planning_bot.access import allowed
from meal_planning_bot.config import Config, ConfigError, load_config
from meal_planning_bot.db import open_database
from meal_planning_bot.formatting import COMMANDS
from meal_planning_bot.handlers.catalog import (
    cmd_dish,
    cmd_dishes,
    cmd_foods,
    cmd_restore,
    on_catalog_callback,
)
from meal_planning_bot.handlers.help import cmd_help, cmd_myid, cmd_start, cmd_unknown
from meal_planning_bot.handlers.plan import (
    cmd_plan,
    cmd_regenerate,
    cmd_shopping,
    cmd_swap,
    cmd_today,
)
from meal_planning_bot.handlers.settings import cmd_set, cmd_settings
from meal_planning_bot.handlers.wizards import (
    cmd_cancel,
    cmd_deletedish,
    cmd_deletefood,
    cmd_editdish,
    cmd_editfood,
    cmd_newdish,
    cmd_newfood,
    on_wizard_callback,
    on_wizard_message,
)
from meal_planning_bot.telegram_bridge import (
    bridge,
    bridge_wizard_text,
)
from meal_planning_bot.weeks import current_week_start, next_week_start

# Every generic parameter of `Application`/`CallbackContext` is left at PTB's
# own default shape here (plain dicts for bot_data/user_data/chat_data); this
# alias just keeps the six-way generic out of every signature below.
Application = PTBApplication[Any, Any, Any, Any, Any, Any]

_CATALOG_CALLBACK_PATTERN = r"^(dishes|foods|dish|restore):"
_WIZARD_CALLBACK_PATTERN = (
    r"^(meal|ing|ingfood|unit|cat|kcalref|steps|kcal|confirm|wizdish|wizfood"
    r"|field|ffield|deletedish|deletefood):"
)


def _register_handlers(app: Application, config: Config) -> None:
    gate = allowed(config)

    for name, handler in (
        ("start", cmd_start),
        ("help", cmd_help),
        ("plan", cmd_plan),
        ("today", cmd_today),
        ("shopping", cmd_shopping),
        ("regenerate", cmd_regenerate),
        ("swap", cmd_swap),
        ("dishes", cmd_dishes),
        ("dish", cmd_dish),
        ("foods", cmd_foods),
        ("restore", cmd_restore),
        ("newdish", cmd_newdish),
        ("editdish", cmd_editdish),
        ("deletedish", cmd_deletedish),
        ("newfood", cmd_newfood),
        ("editfood", cmd_editfood),
        ("deletefood", cmd_deletefood),
        ("cancel", cmd_cancel),
        ("settings", cmd_settings),
        ("set", cmd_set),
    ):
        app.add_handler(CommandHandler(name, bridge(gate(handler))))

    # /myid is the only command exempt from `allowed`: it must answer any user
    # so they can discover the ID they need added to the allow-list.
    app.add_handler(CommandHandler("myid", bridge(cmd_myid)))

    # Each `gate(...)` call is bound to a name before use: mypy's ParamSpec
    # unification for `allowed`'s decorator does not resolve correctly when
    # its result feeds directly into another call's argument position.
    gated_unknown = gate(cmd_unknown)
    app.add_handler(MessageHandler(filters.COMMAND, bridge(gated_unknown)))

    gated_wizard_message = gate(on_wizard_message)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bridge_wizard_text(gated_wizard_message))
    )

    gated_catalog_callback = gate(on_catalog_callback)
    app.add_handler(
        CallbackQueryHandler(bridge(gated_catalog_callback), pattern=_CATALOG_CALLBACK_PATTERN)
    )

    gated_wizard_callback = gate(on_wizard_callback)
    app.add_handler(
        CallbackQueryHandler(bridge(gated_wizard_callback), pattern=_WIZARD_CALLBACK_PATTERN)
    )


async def _post_my_commands(app: Application) -> None:
    await app.bot.set_my_commands(
        [BotCommand(command.name, command.description) for command in COMMANDS]
    )


def build_application(
    config: Config,
    conn: Connection,
    *,
    bot: "ExtBot[None] | None" = None,
    clock: Callable[[], date] = date.today,
) -> Application:
    if bot is not None:
        builder = ApplicationBuilder().bot(bot)
    else:
        builder = ApplicationBuilder().token(config.token)
    app: Application = builder.post_init(_post_my_commands).build()

    app.bot_data["conn"] = conn
    app.bot_data["clock"] = clock
    app.bot_data["rng"] = Random()
    app.bot_data["reschedule"] = lambda key: scheduler.reschedule(
        _job_queue(app), conn, config, key
    )

    _register_handlers(app, config)
    return app


async def _post_catch_up(app: Application, conn: Connection, config: Config, today: date) -> None:
    for plan in scheduler.startup_catch_up(conn, config, today):
        if plan.week_start == current_week_start(today):
            await scheduler.post_plan_and_day(app.bot, config, conn, plan, today.weekday())
        elif plan.week_start == next_week_start(today):
            await scheduler.post_plan_and_shopping(app.bot, config, conn, plan)


# httpx logs every request at INFO including the full URL, and the Telegram Bot API
# puts the token in the path -- so INFO-level httpx prints the token on every poll,
# forever, into whatever collects the container's logs. apscheduler is merely noisy.
_MUZZLED_LOGGERS = ("httpx", "httpcore", "apscheduler")


def _configure_logging(config: Config) -> None:
    logging.basicConfig(level=config.log_level)
    for name in _MUZZLED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    try:
        config = load_config(os.environ)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)

    _configure_logging(config)
    conn = open_database(config.db_path)
    app = build_application(config, conn)

    today = date.today()
    previous_post_init = app.post_init

    async def _post_init(built_app: Application) -> None:
        if previous_post_init is not None:
            await previous_post_init(built_app)
        await _post_catch_up(built_app, conn, config, today)

    app.post_init = _post_init
    scheduler.register_jobs(_job_queue(app), conn, config)

    app.run_polling()


def _job_queue(app: Application) -> scheduler.JobQueueLike:
    # `telegram.ext.JobQueue` genuinely satisfies `JobQueueLike` at runtime;
    # mypy's structural matching for callable Protocol members does not cope
    # with `run_daily`'s extra defaulted keyword-only parameters, hence the cast.
    assert app.job_queue is not None
    return cast(scheduler.JobQueueLike, app.job_queue)


if __name__ == "__main__":
    main()
