import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time
from random import Random
from sqlite3 import Connection
from typing import Protocol
from zoneinfo import ZoneInfo

from meal_planning_bot import repo
from meal_planning_bot.config import Config
from meal_planning_bot.formatting import (
    render_day,
    render_plan,
    render_planner_failure,
    render_shopping,
)
from meal_planning_bot.handlers import load_all_foods, load_dishes_for_plan
from meal_planning_bot.models import Plan
from meal_planning_bot.planner import PlannerFailure, plan_week
from meal_planning_bot.shopping import aggregate
from meal_planning_bot.weeks import current_week_start, next_week_start

logger = logging.getLogger(__name__)


class BotLike(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object: ...


class JobLike(Protocol):
    def schedule_removal(self) -> None: ...


class JobContextLike(Protocol):
    bot: BotLike


JobCallback = Callable[[JobContextLike], Awaitable[None]]


class JobQueueLike(Protocol):
    def run_daily(
        self,
        callback: JobCallback,
        time: time,
        days: tuple[int, ...],
        name: str | None = None,
    ) -> JobLike: ...

    def get_jobs_by_name(self, name: str) -> tuple[JobLike, ...]: ...


_JOB_FOR_SETTING: dict[str, str] = {
    "weekly_post_weekday": "weekly",
    "weekly_post_time": "weekly",
    "daily_post_time": "daily",
}


def parse_local_time(raw: str, tz: ZoneInfo) -> time:
    hour, minute = (int(p) for p in raw.split(":"))
    return time(hour=hour, minute=minute, tzinfo=tz)


def _generate_plan(conn: Connection, week_start: date, today: date, rng: Random) -> Plan:
    catalogue = repo.list_dishes(conn, archived=False)
    # `around=today` gives scheduled_history a +-60 day window, which always
    # includes the just-saved current week even when week_start is next
    # week's Monday -- that is what makes the cooldown span the boundary.
    history = repo.scheduled_history(conn, today)
    settings = repo.planner_settings(conn)
    plan = plan_week(catalogue, history, settings, week_start, rng)
    repo.save_plan(conn, plan)
    return plan


async def _send(bot: BotLike, config: Config, text: str) -> None:
    try:
        await bot.send_message(chat_id=config.group_chat_id, text=text)
    except Exception:
        logger.exception("failed to send scheduled message")


async def post_plan_and_shopping(
    bot: BotLike, config: Config, conn: Connection, plan: Plan
) -> None:
    dishes = load_dishes_for_plan(conn, plan)
    foods = load_all_foods(conn)
    await _send(bot, config, render_plan(plan, dishes, is_next_week=True))
    for message in render_shopping(aggregate(plan, dishes, foods)):
        await _send(bot, config, message)


async def post_plan_and_day(
    bot: BotLike, config: Config, conn: Connection, plan: Plan, day: int
) -> None:
    dishes = load_dishes_for_plan(conn, plan)
    await _send(bot, config, render_plan(plan, dishes, is_next_week=False))
    await _send(bot, config, render_day(plan, dishes, day))


async def weekly_job(
    bot: BotLike, conn: Connection, config: Config, today: date, rng: Random
) -> None:
    week_start = next_week_start(today)
    plan = repo.get_plan(conn, week_start)
    if plan is None:
        try:
            plan = _generate_plan(conn, week_start, today, rng)
        except PlannerFailure as failure:
            # The group is the right place for this: the reason there is no plan
            # is that the catalogue cannot support one, and the people reading
            # are the people who can fix it with /newdish.
            await _send(bot, config, render_planner_failure(failure.diagnosis))
            return
    await post_plan_and_shopping(bot, config, conn, plan)


async def daily_job(
    bot: BotLike, conn: Connection, config: Config, today: date, rng: Random
) -> None:
    week_start = current_week_start(today)
    plan = repo.get_plan(conn, week_start)
    if plan is None:
        try:
            plan = _generate_plan(conn, week_start, today, rng)
        except PlannerFailure as failure:
            await _send(bot, config, render_planner_failure(failure.diagnosis))
            return
        await post_plan_and_day(bot, config, conn, plan, today.weekday())
        return
    dishes = load_dishes_for_plan(conn, plan)
    await _send(bot, config, render_day(plan, dishes, today.weekday()))


def _register_weekly(job_queue: JobQueueLike, conn: Connection, config: Config) -> None:
    tz = ZoneInfo(config.timezone)
    weekday = int(repo.get_setting(conn, "weekly_post_weekday"))
    post_time = parse_local_time(repo.get_setting(conn, "weekly_post_time"), tz)

    async def _job(context: JobContextLike) -> None:
        today = datetime.now(tz).date()
        await weekly_job(context.bot, conn, config, today, Random())

    job_queue.run_daily(_job, post_time, days=(weekday,), name="weekly")


def _register_daily(job_queue: JobQueueLike, conn: Connection, config: Config) -> None:
    tz = ZoneInfo(config.timezone)
    post_time = parse_local_time(repo.get_setting(conn, "daily_post_time"), tz)

    async def _job(context: JobContextLike) -> None:
        today = datetime.now(tz).date()
        await daily_job(context.bot, conn, config, today, Random())

    job_queue.run_daily(_job, post_time, days=(0, 1, 2, 3, 4), name="daily")


def register_jobs(job_queue: JobQueueLike, conn: Connection, config: Config) -> None:
    _register_weekly(job_queue, conn, config)
    _register_daily(job_queue, conn, config)


def reschedule(job_queue: JobQueueLike, conn: Connection, config: Config, key: str) -> None:
    job_name = _JOB_FOR_SETTING.get(key)
    if job_name is None:
        return
    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    if job_name == "weekly":
        _register_weekly(job_queue, conn, config)
    else:
        _register_daily(job_queue, conn, config)


def startup_catch_up(conn: Connection, config: Config, today: date) -> list[Plan]:
    """Generate the weeks that should already exist, skipping any that cannot be drawn.

    A PlannerFailure here must never reach the caller. This runs inside post_init, so
    an exception kills the process before polling starts -- and on a brand new database
    the catalogue is empty, so it always fails. That is a deadlock: the catalogue can
    only be filled through the bot, and the bot will not start until the catalogue is
    filled. Logging and carrying on is the only behaviour that lets a fresh deployment
    reach the point where someone can send /newdish.
    """
    generated: list[Plan] = []
    rng = Random()

    current_start = current_week_start(today)
    if today.weekday() < 5 and repo.get_plan(conn, current_start) is None:
        _try_generate(conn, current_start, today, rng, generated)

    weekly_weekday = int(repo.get_setting(conn, "weekly_post_weekday"))
    next_start = next_week_start(today)
    if today.weekday() >= weekly_weekday and repo.get_plan(conn, next_start) is None:
        _try_generate(conn, next_start, today, rng, generated)

    return generated


def _try_generate(
    conn: Connection, week_start: date, today: date, rng: Random, into: list[Plan]
) -> None:
    try:
        into.append(_generate_plan(conn, week_start, today, rng))
    except PlannerFailure as failure:
        logger.warning("no plan for week of %s: %s", week_start, failure.diagnosis)
