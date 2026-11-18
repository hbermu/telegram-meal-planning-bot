"""One menu message per chat.

Every reply is rendered onto a single message per chat, edited in place, and the
message that asked for it is deleted. Checking the plan and walking the
catalogue leave one message behind instead of a screenful, and the content the
bot was asked to produce -- a shopping list, a scheduled post -- stays readable
among its own messages instead of being buried under dead menus.

The state is one message id per chat, held in memory on purpose: losing it in a
restart costs one extra message and nothing else, because a tap adopts the
message it came from and editing in place resumes by itself.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from meal_planning_bot.handlers import Keyboard

logger = logging.getLogger(__name__)


class TransportError(Exception):
    """A Telegram call that did not go through, raised by the bridge so this
    module and the handlers never see a `telegram` exception type."""


class NotModified(TransportError):
    """An edit that would leave the message exactly as it is. Telegram answers
    400 to it, and re-rendering the same menu is what refreshing does, so it is
    a success and not a dead message."""


class BotLike(Protocol):
    async def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None) -> int: ...
    async def edit_message(
        self, chat_id: int, message_id: int, text: str, keyboard: Keyboard | None
    ) -> None: ...
    async def delete_message(self, chat_id: int, message_id: int) -> None: ...


@dataclass(frozen=True)
class Trigger:
    """What an update brings in: the user message that asked for a reply and
    must come off the screen, and the bot message a tap arrived on, which
    becomes the anchor when nothing else is held."""

    chat_id: int
    message_id: int | None
    carrier_id: int | None


async def delete_quietly(bot: BotLike, chat_id: int, message_id: int) -> None:
    # Telegram refuses a deletion after 48 hours and, in a group, without the
    # delete-messages right. Neither is a reason to interrupt navigation, so the
    # worst case is a message that stays on screen.
    try:
        await bot.delete_message(chat_id, message_id)
    except TransportError as exc:
        logger.debug("could not delete %s in %s: %s", message_id, chat_id, exc)


class Anchors:
    def __init__(self) -> None:
        self._held: dict[int, int] = {}

    async def show(
        self, bot: BotLike, trigger: Trigger, text: str, keyboard: Keyboard | None = None
    ) -> None:
        await self._consume(bot, trigger)
        chat_id = trigger.chat_id
        held = self._held.get(chat_id)
        if held is not None:
            try:
                await bot.edit_message(chat_id, held, text, keyboard)
                return
            except NotModified:
                return
            except TransportError as exc:
                logger.debug("anchor %s in %s is no longer editable: %s", held, chat_id, exc)
                del self._held[chat_id]
                await delete_quietly(bot, chat_id, held)
        self._held[chat_id] = await bot.send_message(chat_id, text, keyboard)

    async def send(self, bot: BotLike, trigger: Trigger, text: str) -> None:
        """Post content that is not a menu. It stays in the chat as a message of
        its own and the anchor keeps showing whatever it was showing."""
        await self._consume(bot, trigger)
        await bot.send_message(trigger.chat_id, text, None)

    async def _consume(self, bot: BotLike, trigger: Trigger) -> None:
        if trigger.carrier_id is not None:
            self._held.setdefault(trigger.chat_id, trigger.carrier_id)
        if trigger.message_id is not None:
            await delete_quietly(bot, trigger.chat_id, trigger.message_id)
