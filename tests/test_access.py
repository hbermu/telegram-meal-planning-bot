import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from meal_planning_bot.access import allowed, private_only
from meal_planning_bot.config import Config
from meal_planning_bot.formatting import PRIVATE_ONLY_MESSAGE

TOKEN = "123456:super-secret-token"

CONFIG = Config(
    token=TOKEN,
    allowed_user_ids=frozenset({1, 2}),
    group_chat_id=-1001,
    db_path=Path("/data/mealbot.db"),
    timezone="UTC",
    log_level="INFO",
)


@dataclass
class FakeChat:
    id: int
    type: str


@dataclass
class FakeUpdate:
    effective_user: SimpleNamespace | None
    effective_chat: FakeChat | None
    replies: list[str] = field(default_factory=list)

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


async def _handler(update: FakeUpdate) -> None:
    update.replies.append("handled")


def _run(coro: Any) -> None:
    asyncio.run(coro)


def test_disallowed_user_gets_no_reply_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    update = FakeUpdate(
        effective_user=SimpleNamespace(id=999),
        effective_chat=FakeChat(id=-1001, type="group"),
    )
    wrapped = allowed(CONFIG)(_handler)
    with caplog.at_level(logging.INFO):
        _run(wrapped(update))
    assert update.replies == []
    assert "999" in caplog.text


def test_allowed_user_in_unknown_chat_gets_no_reply() -> None:
    update = FakeUpdate(
        effective_user=SimpleNamespace(id=1),
        effective_chat=FakeChat(id=-555, type="group"),
    )
    wrapped = allowed(CONFIG)(_handler)
    _run(wrapped(update))
    assert update.replies == []


def test_allowed_user_in_group_chat_runs_the_handler() -> None:
    update = FakeUpdate(
        effective_user=SimpleNamespace(id=1),
        effective_chat=FakeChat(id=-1001, type="group"),
    )
    wrapped = allowed(CONFIG)(_handler)
    _run(wrapped(update))
    assert update.replies == ["handled"]


def test_allowed_user_in_private_chat_runs_the_handler() -> None:
    update = FakeUpdate(
        effective_user=SimpleNamespace(id=2),
        effective_chat=FakeChat(id=42, type="private"),
    )
    wrapped = allowed(CONFIG)(_handler)
    _run(wrapped(update))
    assert update.replies == ["handled"]


def test_allowed_wrapper_is_marked_access_gated() -> None:
    wrapped = allowed(CONFIG)(_handler)
    assert getattr(wrapped, "__access_gated__", False) is True


def test_private_only_rejects_from_the_group_with_redirect() -> None:
    update = FakeUpdate(
        effective_user=SimpleNamespace(id=1),
        effective_chat=FakeChat(id=-1001, type="group"),
    )
    wrapped = private_only(_handler)
    _run(wrapped(update))
    assert update.replies == [PRIVATE_ONLY_MESSAGE]


def test_private_only_runs_the_handler_in_private() -> None:
    update = FakeUpdate(
        effective_user=SimpleNamespace(id=1),
        effective_chat=FakeChat(id=42, type="private"),
    )
    wrapped = private_only(_handler)
    _run(wrapped(update))
    assert update.replies == ["handled"]


def test_no_log_record_ever_carries_the_token_allow_list_or_group_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    updates = [
        FakeUpdate(
            effective_user=SimpleNamespace(id=999), effective_chat=FakeChat(id=1, type="group")
        ),
        FakeUpdate(
            effective_user=SimpleNamespace(id=1), effective_chat=FakeChat(id=-555, type="group")
        ),
        FakeUpdate(
            effective_user=SimpleNamespace(id=1), effective_chat=FakeChat(id=-1001, type="group")
        ),
    ]
    wrapped = allowed(CONFIG)(_handler)
    with caplog.at_level(logging.DEBUG):
        for update in updates:
            _run(wrapped(update))
    assert any(record.getMessage() for record in caplog.records)
    for record in caplog.records:
        message = record.getMessage()
        assert TOKEN not in message
        assert str(CONFIG.group_chat_id) not in message
        assert repr(CONFIG.allowed_user_ids) not in message


def test_third_party_loggers_cannot_print_the_token(caplog: pytest.LogCaptureFixture) -> None:
    """httpx logs every request URL at INFO, and the Telegram API carries the token
    in the path. Our own logging is careful; a dependency's is not, so the entry
    point has to silence it or the token lands in the container logs on every poll."""
    from meal_planning_bot.__main__ import _MUZZLED_LOGGERS, _configure_logging

    assert "httpx" in _MUZZLED_LOGGERS

    _configure_logging(CONFIG)
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpx").info(
            "HTTP Request: POST https://api.telegram.org/bot%s/getMe", CONFIG.token
        )

    assert CONFIG.token not in caplog.text
