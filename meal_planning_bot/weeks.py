from collections.abc import Sequence
from datetime import date, timedelta

NEXT_KEYWORD = "siguiente"


class ArgumentError(Exception):
    pass


def current_week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def next_week_start(today: date) -> date:
    return current_week_start(today) + timedelta(days=7)


def resolve_week(args: Sequence[str], today: date) -> tuple[date, bool]:
    if not args:
        return current_week_start(today), False
    if len(args) == 1 and args[0] == NEXT_KEYWORD:
        return next_week_start(today), True
    raise ArgumentError(f"unknown argument: {args[0]!r}")
