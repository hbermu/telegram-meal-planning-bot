import asyncio
import sqlite3
from collections.abc import Awaitable
from datetime import date
from typing import TypeVar

import pytest

from meal_planning_bot import repo
from meal_planning_bot.config import Config
from meal_planning_bot.formatting import (
    PRIVATE_ONLY_MESSAGE,
    SET_USAGE_MESSAGE,
    render_setting_changed,
)
from meal_planning_bot.handlers.settings import cmd_set, cmd_settings
from meal_planning_bot.migrations import SEEDED_SETTINGS
from meal_planning_bot.repo import SETTING_SPECS, IntSpec, SettingError, TimeSpec
from tests.test_handlers import _context, _update

_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)


def test_setting_specs_match_seeded_settings_keys() -> None:
    assert SETTING_SPECS.keys() == SEEDED_SETTINGS.keys()


def test_setting_specs_never_expose_environment_provided_values() -> None:
    env_field_names = {f.name for f in Config.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert SETTING_SPECS.keys() & env_field_names == set()
    # spelled out explicitly, since the spec names these five by name
    forbidden = {"token", "allowed_user_ids", "group_chat_id", "db_path", "timezone"}
    assert SETTING_SPECS.keys() & forbidden == set()


@pytest.mark.parametrize("key", SETTING_SPECS.keys())
def test_int_settings_reject_out_of_range(key: str, conn: sqlite3.Connection) -> None:
    spec = SETTING_SPECS[key]
    if not isinstance(spec, IntSpec):
        pytest.skip("not an integer setting")
    with pytest.raises(SettingError):
        repo.set_setting(conn, key, str(spec.low - 1))
    with pytest.raises(SettingError):
        repo.set_setting(conn, key, str(spec.high + 1))


@pytest.mark.parametrize("key", SETTING_SPECS.keys())
def test_int_settings_accept_boundaries(key: str, conn: sqlite3.Connection) -> None:
    spec = SETTING_SPECS[key]
    if not isinstance(spec, IntSpec):
        pytest.skip("not an integer setting")
    old, new = repo.set_setting(conn, key, str(spec.low))
    assert new == str(spec.low)
    old, new = repo.set_setting(conn, key, str(spec.high))
    assert new == str(spec.high)


@pytest.mark.parametrize("key", ["weekly_post_time", "daily_post_time"])
def test_time_settings_accept_valid_and_reject_invalid(key: str, conn: sqlite3.Connection) -> None:
    old, new = repo.set_setting(conn, key, "07:30")
    assert new == "07:30"
    with pytest.raises(SettingError):
        repo.set_setting(conn, key, "24:00")
    with pytest.raises(SettingError):
        repo.set_setting(conn, key, "not-a-time")


def test_int_setting_rejects_non_integer(conn: sqlite3.Connection) -> None:
    with pytest.raises(SettingError):
        repo.set_setting(conn, "daily_kcal_target", "a lot")


def test_unknown_key_raises_and_changes_nothing(conn: sqlite3.Connection) -> None:
    before = repo.all_settings(conn)
    with pytest.raises(SettingError):
        repo.set_setting(conn, "not_a_real_setting", "1")
    assert repo.all_settings(conn) == before


def test_bad_value_changes_nothing(conn: sqlite3.Connection) -> None:
    before = repo.get_setting(conn, "daily_kcal_target")
    with pytest.raises(SettingError):
        repo.set_setting(conn, "daily_kcal_target", "99999")
    assert repo.get_setting(conn, "daily_kcal_target") == before


def test_set_setting_returns_old_and_new(conn: sqlite3.Connection) -> None:
    old, new = repo.set_setting(conn, "daily_kcal_target", "2200")
    assert old == "2000"
    assert new == "2200"
    assert repo.get_setting(conn, "daily_kcal_target") == "2200"


def test_get_setting_unknown_key_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(SettingError):
        repo.get_setting(conn, "not_a_real_setting")


def test_all_settings_returns_every_seeded_key_with_value_and_default(
    conn: sqlite3.Connection,
) -> None:
    rows = repo.all_settings(conn)
    assert len(rows) == len(SEEDED_SETTINGS)
    as_dict = {key: (value, default) for key, value, default in rows}
    assert as_dict["daily_kcal_target"] == ("2000", "2000")
    repo.set_setting(conn, "daily_kcal_target", "2500")
    as_dict = {key: (value, default) for key, value, default in repo.all_settings(conn)}
    assert as_dict["daily_kcal_target"] == ("2500", "2000")


def test_planner_settings_reads_all_keys(conn: sqlite3.Connection) -> None:
    from meal_planning_bot.models import MealType

    settings = repo.planner_settings(conn)
    assert settings.daily_kcal_target == 2000
    assert settings.kcal_tolerance_pct == 10
    assert settings.max_food_repeats_per_day == 2
    assert settings.cooldown_days[MealType.LUNCH] == 14
    assert settings.cooldown_days[MealType.BREAKFAST] == 1


def test_time_spec_type_present() -> None:
    assert isinstance(SETTING_SPECS["weekly_post_time"], TimeSpec)


# --- /settings and /set handlers --------------------------------------------


def _today() -> date:
    return date(2026, 9, 21)


def test_cmd_settings_lists_every_key_with_value_and_default(conn: sqlite3.Connection) -> None:
    repo.set_setting(conn, "daily_kcal_target", "2500")
    update = _update()
    _run(cmd_settings(update, _context(conn, _today())))
    text = update.replies[0]
    for key, value, default in repo.all_settings(conn):
        assert key in text
        assert value in text
        assert default in text


def test_set_stores_and_confirms_with_old_and_new_value(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_set(update, _context(conn, _today(), ["daily_kcal_target", "2200"])))
    assert update.replies == [render_setting_changed("daily_kcal_target", "2000", "2200")]
    assert repo.get_setting(conn, "daily_kcal_target") == "2200"


def test_set_unknown_key_lists_valid_keys_and_changes_nothing(conn: sqlite3.Connection) -> None:
    before = repo.all_settings(conn)
    update = _update()
    _run(cmd_set(update, _context(conn, _today(), ["not_a_real_setting", "1"])))
    for key in SETTING_SPECS:
        assert key in update.replies[0]
    assert repo.all_settings(conn) == before


def test_set_out_of_range_shows_accepted_range_and_changes_nothing(
    conn: sqlite3.Connection,
) -> None:
    before = repo.get_setting(conn, "daily_kcal_target")
    update = _update()
    _run(cmd_set(update, _context(conn, _today(), ["daily_kcal_target", "99999"])))
    assert "800" in update.replies[0]
    assert "6000" in update.replies[0]
    assert repo.get_setting(conn, "daily_kcal_target") == before


def test_set_bad_time_shows_the_expected_format_and_changes_nothing(
    conn: sqlite3.Connection,
) -> None:
    before = repo.get_setting(conn, "weekly_post_time")
    update = _update()
    _run(cmd_set(update, _context(conn, _today(), ["weekly_post_time", "not-a-time"])))
    assert "HH:MM" in update.replies[0]
    assert repo.get_setting(conn, "weekly_post_time") == before


def test_set_usage_message_when_missing_arguments(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_set(update, _context(conn, _today(), ["daily_kcal_target"])))
    assert update.replies == [SET_USAGE_MESSAGE]


def test_set_weekday_reschedules_the_affected_job(conn: sqlite3.Connection) -> None:
    calls: list[str] = []
    context = _context(conn, _today(), ["weekly_post_weekday", "6"])
    context.bot_data["reschedule"] = lambda key: calls.append(key)
    update = _update()
    _run(cmd_set(update, context))
    assert repo.get_setting(conn, "weekly_post_weekday") == "6"
    assert calls == ["weekly_post_weekday"]


def test_set_non_schedule_key_does_not_reschedule(conn: sqlite3.Connection) -> None:
    calls: list[str] = []
    context = _context(conn, _today(), ["daily_kcal_target", "2200"])
    context.bot_data["reschedule"] = lambda key: calls.append(key)
    update = _update()
    _run(cmd_set(update, context))
    assert calls == []


def test_set_tolerates_a_missing_reschedule_hook(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_set(update, _context(conn, _today(), ["weekly_post_time", "07:30"])))
    assert repo.get_setting(conn, "weekly_post_time") == "07:30"


def test_set_is_rejected_outside_a_private_chat(conn: sqlite3.Connection) -> None:
    update = _update(chat_id=-1001, chat_type="group")
    _run(cmd_set(update, _context(conn, _today(), ["daily_kcal_target", "2200"])))
    assert update.replies == [PRIVATE_ONLY_MESSAGE]
    assert repo.get_setting(conn, "daily_kcal_target") == "2000"
