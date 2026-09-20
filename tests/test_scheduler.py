import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from random import Random
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from meal_planning_bot import repo, scheduler
from meal_planning_bot.config import Config
from meal_planning_bot.db import apply_pragmas, migrate
from meal_planning_bot.models import Category, DishIngredient, MealType, Unit
from meal_planning_bot.planner import plan_week
from meal_planning_bot.repo import planner_settings
from meal_planning_bot.weeks import current_week_start, next_week_start

OTHER_CHAT_ID = -9999

CONFIG = Config(
    token="test-token",
    allowed_user_ids=frozenset({1}),
    group_chat_id=-1001,
    db_path=Path("/tmp/unused.db"),
    timezone="America/New_York",  # a DST zone: the offset test below needs one
    log_level="INFO",
)


def _run(coro: Any) -> None:
    asyncio.run(coro)


def _seed_food(conn: sqlite3.Connection, name: str) -> int:
    food = repo.create_food(conn, name=name, unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    return food.id


def _seed_full_catalogue(conn: sqlite3.Connection) -> None:
    counts = {MealType.BREAKFAST: 6, MealType.SNACK: 12, MealType.LUNCH: 6, MealType.DINNER: 6}
    for meal_type, count in counts.items():
        for i in range(count):
            food_id = _seed_food(conn, name=f"{meal_type.value}-food-{i}")
            repo.create_dish(
                conn,
                name=f"{meal_type.value}-{i}",
                meal_type=meal_type,
                ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
                kcal_override=400,
            )


def _seed_plan(conn: sqlite3.Connection, week_start: date, seed: int = 1) -> None:
    catalogue = repo.list_dishes(conn, archived=False)
    plan = plan_week(catalogue, [], planner_settings(conn), week_start, Random(seed))
    repo.save_plan(conn, plan)


@dataclass
class FakeBot:
    sent: list[tuple[int, str]] = field(default_factory=list)
    fail_next: bool = False

    async def send_message(self, chat_id: int, text: str) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated Telegram outage")
        self.sent.append((chat_id, text))


@dataclass
class FakeJob:
    name: str
    removed: bool = False

    def schedule_removal(self) -> None:
        self.removed = True


@dataclass
class FakeJobQueue:
    registered: list[tuple[Any, Any, tuple[int, ...], str | None]] = field(default_factory=list)
    jobs: list[FakeJob] = field(default_factory=list)

    def run_daily(
        self, callback: Any, time: Any, days: tuple[int, ...], name: str | None = None
    ) -> FakeJob:
        self.registered.append((callback, time, days, name))
        job = FakeJob(name=name or "")
        self.jobs.append(job)
        return job

    def get_jobs_by_name(self, name: str) -> tuple[FakeJob, ...]:
        return tuple(j for j in self.jobs if j.name == name and not j.removed)


@pytest.fixture
def conn() -> Any:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_pragmas(connection)
    migrate(connection)
    yield connection
    connection.close()


# --- parse_local_time / DST ------------------------------------------------


def test_parse_local_time_is_timezone_aware() -> None:
    tz = ZoneInfo("America/New_York")
    t = scheduler.parse_local_time("08:30", tz)
    assert t.hour == 8
    assert t.minute == 30
    assert t.tzinfo is tz


def test_parse_local_time_lands_on_the_same_wall_clock_across_dst() -> None:
    # America/New_York is UTC-5 in January (EST) and UTC-4 in July (EDT). A
    # naive time would keep a fixed UTC offset and drift by an hour across
    # the boundary; a tz-aware time recomputes the offset for each date.
    tz = ZoneInfo("America/New_York")
    t = scheduler.parse_local_time("08:00", tz)

    january = datetime.combine(date(2026, 1, 15), t)
    july = datetime.combine(date(2026, 7, 15), t)

    january_offset = january.utcoffset()
    july_offset = july.utcoffset()

    assert january_offset is not None
    assert july_offset is not None
    assert january_offset != july_offset
    assert january.hour == july.hour == 8


# --- register_jobs ----------------------------------------------------------


def test_register_jobs_names_and_days(conn: sqlite3.Connection) -> None:
    job_queue = FakeJobQueue()
    scheduler.register_jobs(job_queue, conn, CONFIG)

    names = {entry[3] for entry in job_queue.registered}
    assert names == {"weekly", "daily"}

    weekly = next(e for e in job_queue.registered if e[3] == "weekly")
    daily = next(e for e in job_queue.registered if e[3] == "daily")

    assert weekly[2] == (4,)  # default weekly_post_weekday is Friday
    assert daily[2] == (0, 1, 2, 3, 4)
    assert weekly[1].tzinfo is not None
    assert daily[1].tzinfo is not None


def test_register_jobs_honours_a_changed_weekday(conn: sqlite3.Connection) -> None:
    repo.set_setting(conn, "weekly_post_weekday", "1")
    job_queue = FakeJobQueue()
    scheduler.register_jobs(job_queue, conn, CONFIG)
    weekly = next(e for e in job_queue.registered if e[3] == "weekly")
    assert weekly[2] == (1,)


# --- reschedule --------------------------------------------------------------


def test_reschedule_replaces_only_the_affected_job(conn: sqlite3.Connection) -> None:
    job_queue = FakeJobQueue()
    scheduler.register_jobs(job_queue, conn, CONFIG)
    original_weekly = job_queue.get_jobs_by_name("weekly")[0]
    original_daily = job_queue.get_jobs_by_name("daily")[0]

    repo.set_setting(conn, "daily_post_time", "09:30")
    scheduler.reschedule(job_queue, conn, CONFIG, "daily_post_time")

    assert original_weekly.removed is False
    assert original_daily.removed is True
    new_daily = job_queue.get_jobs_by_name("daily")[0]
    assert new_daily is not original_daily

    daily_entry = next(e for e in reversed(job_queue.registered) if e[3] == "daily")
    assert daily_entry[1].hour == 9
    assert daily_entry[1].minute == 30


def test_reschedule_ignores_an_unrelated_key(conn: sqlite3.Connection) -> None:
    job_queue = FakeJobQueue()
    scheduler.register_jobs(job_queue, conn, CONFIG)
    before = len(job_queue.registered)
    scheduler.reschedule(job_queue, conn, CONFIG, "daily_kcal_target")
    assert len(job_queue.registered) == before


# --- weekly_job ---------------------------------------------------------------


def test_weekly_job_generates_and_posts_next_week_with_shopping_list(
    conn: sqlite3.Connection,
) -> None:
    _seed_full_catalogue(conn)
    bot = FakeBot()
    today = date(2026, 9, 18)  # a Friday
    _run(scheduler.weekly_job(bot, conn, CONFIG, today, Random(7)))

    week_start = next_week_start(today)
    saved = repo.get_plan(conn, week_start)
    assert saved is not None

    assert bot.sent, "expected at least one scheduled message"
    assert {chat_id for chat_id, _ in bot.sent} == {CONFIG.group_chat_id}
    assert OTHER_CHAT_ID not in {chat_id for chat_id, _ in bot.sent}

    plan_message = bot.sent[0][1]
    assert "Plan de la semana que viene" in plan_message
    assert f"{week_start:%d/%m}" in plan_message
    assert len(bot.sent) >= 2  # plan, then at least one shopping-list message


def test_weekly_job_does_not_regenerate_an_existing_plan(conn: sqlite3.Connection) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 18)
    week_start = next_week_start(today)
    _seed_plan(conn, week_start, seed=11)
    before = repo.get_plan(conn, week_start)
    assert before is not None

    bot = FakeBot()
    _run(scheduler.weekly_job(bot, conn, CONFIG, today, Random(1)))

    after = repo.get_plan(conn, week_start)
    assert after == before


def test_weekly_job_passes_current_week_entries_as_history(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 18)  # Friday
    current_start = current_week_start(today)
    _seed_plan(conn, current_start, seed=3)
    current_plan = repo.get_plan(conn, current_start)
    assert current_plan is not None
    current_dish_ids = {e.dish_id for e in current_plan.entries}

    captured: dict[str, Any] = {}
    real_plan_week = scheduler.plan_week

    def _spy(catalogue: Any, history: Any, settings: Any, week_start: Any, rng: Any) -> Any:
        captured["history"] = list(history)
        return real_plan_week(catalogue, history, settings, week_start, rng)

    monkeypatch.setattr(scheduler, "plan_week", _spy)

    bot = FakeBot()
    _run(scheduler.weekly_job(bot, conn, CONFIG, today, Random(5)))

    history_dish_ids = {record.dish_id for record in captured["history"]}
    assert current_dish_ids & history_dish_ids


# --- daily_job -----------------------------------------------------------------


def test_daily_job_posts_only_the_day_when_a_plan_already_exists(
    conn: sqlite3.Connection,
) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 16)  # Wednesday
    week_start = current_week_start(today)
    _seed_plan(conn, week_start, seed=9)

    bot = FakeBot()
    _run(scheduler.daily_job(bot, conn, CONFIG, today, Random(2)))

    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == CONFIG.group_chat_id
    assert "Plan de esta semana" not in text  # only the day, not the full week


def test_daily_job_generates_plan_then_posts_plan_and_day_when_missing(
    conn: sqlite3.Connection,
) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 16)  # Wednesday
    week_start = current_week_start(today)
    assert repo.get_plan(conn, week_start) is None

    bot = FakeBot()
    _run(scheduler.daily_job(bot, conn, CONFIG, today, Random(2)))

    assert repo.get_plan(conn, week_start) is not None
    assert {chat_id for chat_id, _ in bot.sent} == {CONFIG.group_chat_id}
    assert len(bot.sent) == 2
    assert "Plan de esta semana" in bot.sent[0][1]


def test_a_failed_send_is_logged_and_not_retried(conn: sqlite3.Connection) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 16)
    week_start = current_week_start(today)
    _seed_plan(conn, week_start, seed=9)

    bot = FakeBot(fail_next=True)
    _run(scheduler.daily_job(bot, conn, CONFIG, today, Random(2)))

    # The send raised; daily_job must not have re-attempted it.
    assert bot.sent == []


# --- startup_catch_up ------------------------------------------------------


def test_startup_catch_up_generates_current_week_on_a_weekday_wednesday(
    conn: sqlite3.Connection,
) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 16)  # Wednesday, both weeks unplanned
    generated = scheduler.startup_catch_up(conn, CONFIG, today)

    week_starts = {p.week_start for p in generated}
    assert current_week_start(today) in week_starts
    assert next_week_start(today) not in week_starts  # not yet past Friday
    assert repo.get_plan(conn, current_week_start(today)) is not None


def test_startup_catch_up_generates_next_week_on_a_saturday(conn: sqlite3.Connection) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 19)  # Saturday
    current_start = current_week_start(today)
    _seed_plan(conn, current_start, seed=4)  # current week already planned

    generated = scheduler.startup_catch_up(conn, CONFIG, today)

    week_starts = {p.week_start for p in generated}
    assert week_starts == {next_week_start(today)}
    assert repo.get_plan(conn, next_week_start(today)) is not None


def test_startup_catch_up_does_nothing_when_both_weeks_are_already_planned(
    conn: sqlite3.Connection,
) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 16)  # Wednesday, at or past nothing yet for next week
    current_start = current_week_start(today)
    _seed_plan(conn, current_start, seed=6)

    generated = scheduler.startup_catch_up(conn, CONFIG, today)
    assert generated == []


def test_startup_catch_up_does_nothing_on_a_weekend_with_no_current_plan(
    conn: sqlite3.Connection,
) -> None:
    _seed_full_catalogue(conn)
    today = date(2026, 9, 19)  # Saturday, current week has no plan
    current_start = current_week_start(today)
    next_start = next_week_start(today)
    _seed_plan(conn, next_start, seed=8)  # next week already planned

    generated = scheduler.startup_catch_up(conn, CONFIG, today)
    assert generated == []
    assert repo.get_plan(conn, current_start) is None


def test_startup_catch_up_survives_an_empty_catalogue(conn: sqlite3.Connection) -> None:
    """A fresh deployment has no dishes, and the catalogue can only be filled
    through the bot. If this raised, post_init would kill the process before
    polling started and nobody could ever send /newdish."""
    generated = scheduler.startup_catch_up(conn, CONFIG, date(2026, 9, 16))

    assert generated == []
    assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 0


def test_weekly_job_reports_an_empty_catalogue_to_the_group(conn: sqlite3.Connection) -> None:
    bot = FakeBot()
    _run(scheduler.weekly_job(bot, conn, CONFIG, date(2026, 9, 18), Random(0)))

    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == CONFIG.group_chat_id
    assert "desayuno" in text.lower() or "breakfast" in text.lower()
    assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 0


def test_daily_job_reports_an_empty_catalogue_to_the_group(conn: sqlite3.Connection) -> None:
    bot = FakeBot()
    _run(scheduler.daily_job(bot, conn, CONFIG, date(2026, 9, 16), Random(0)))

    assert len(bot.sent) == 1
    assert bot.sent[0][0] == CONFIG.group_chat_id
    assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
