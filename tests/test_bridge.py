from typing import Any

import pytest
from telegram.error import BadRequest, TimedOut

from meal_planning_bot.anchor import NotModified, TransportError
from meal_planning_bot.telegram_bridge import BotAdapter

CHAT = 7
MESSAGE = 99


class RaisingBot:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def edit_message_text(self, **kwargs: Any) -> None:
        raise self._error

    async def delete_message(self, **kwargs: Any) -> None:
        raise self._error


def _adapter(error: Exception) -> BotAdapter:
    # RaisingBot stands in for telegram.Bot: the adapter only calls these two.
    return BotAdapter(RaisingBot(error))  # type: ignore[arg-type]


async def test_an_edit_that_changes_nothing_is_not_an_error() -> None:
    adapter = _adapter(BadRequest("Message is not modified: specified new message content"))
    with pytest.raises(NotModified):
        await adapter.edit_message(CHAT, MESSAGE, "igual", None)


async def test_any_other_bad_request_is_a_transport_error() -> None:
    adapter = _adapter(BadRequest("Message to edit not found"))
    with pytest.raises(TransportError) as raised:
        await adapter.edit_message(CHAT, MESSAGE, "nuevo", None)
    assert not isinstance(raised.value, NotModified)


async def test_a_telegram_failure_never_reaches_a_handler_as_itself() -> None:
    adapter = _adapter(TimedOut())
    with pytest.raises(TransportError):
        await adapter.edit_message(CHAT, MESSAGE, "nuevo", None)
    with pytest.raises(TransportError):
        await adapter.delete_message(CHAT, MESSAGE)
