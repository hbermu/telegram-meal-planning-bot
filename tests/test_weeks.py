from datetime import date

import pytest

from meal_planning_bot.weeks import ArgumentError, current_week_start, next_week_start, resolve_week

MONDAY = date(2026, 9, 21)
FRIDAY = date(2026, 9, 25)
SUNDAY = date(2026, 9, 27)


@pytest.mark.parametrize("today", [MONDAY, FRIDAY, SUNDAY])
def test_current_week_start_is_always_a_monday(today: date) -> None:
    result = current_week_start(today)
    assert result.weekday() == 0
    assert result <= today


def test_current_week_start_values() -> None:
    assert current_week_start(MONDAY) == MONDAY
    assert current_week_start(FRIDAY) == MONDAY
    assert current_week_start(SUNDAY) == MONDAY


@pytest.mark.parametrize("today", [MONDAY, FRIDAY, SUNDAY])
def test_next_week_start_is_seven_days_after_current(today: date) -> None:
    assert next_week_start(today) == current_week_start(today) + (date(2026, 9, 28) - MONDAY)


def test_next_week_start_values() -> None:
    next_monday = date(2026, 9, 28)
    assert next_week_start(MONDAY) == next_monday
    assert next_week_start(FRIDAY) == next_monday
    assert next_week_start(SUNDAY) == next_monday


def test_resolve_week_with_no_args_is_current() -> None:
    assert resolve_week([], FRIDAY) == (MONDAY, False)


def test_resolve_week_with_siguiente_is_next() -> None:
    assert resolve_week(["siguiente"], FRIDAY) == (date(2026, 9, 28), True)


def test_resolve_week_rejects_unknown_argument() -> None:
    with pytest.raises(ArgumentError):
        resolve_week(["proxima"], FRIDAY)
