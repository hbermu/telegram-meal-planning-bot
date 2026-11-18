import functools
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import Bot, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import CallbackContext

from meal_planning_bot.anchor import Anchors, NotModified, TransportError, Trigger
from meal_planning_bot.handlers import CallbackQueryLike, ChatLike, Keyboard, UserLike

_NOT_MODIFIED = "message is not modified"


def to_markup(keyboard: Keyboard | None) -> InlineKeyboardMarkup | None:
    if keyboard is None:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=data) for label, data in row]
            for row in keyboard
        ]
    )


class BotAdapter:
    """Bridges `telegram.Bot` to the narrow transport `anchor.py` expects, and
    turns every `telegram` error into an `anchor` one."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None) -> int:
        message = await self._bot.send_message(
            chat_id=chat_id, text=text, reply_markup=to_markup(keyboard)
        )
        return message.message_id

    async def edit_message(
        self, chat_id: int, message_id: int, text: str, keyboard: Keyboard | None
    ) -> None:
        try:
            await self._bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=to_markup(keyboard),
            )
        except BadRequest as exc:
            if _NOT_MODIFIED in str(exc).lower():
                raise NotModified(str(exc)) from exc
            raise TransportError(str(exc)) from exc
        except TelegramError as exc:
            raise TransportError(str(exc)) from exc

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramError as exc:
            raise TransportError(str(exc)) from exc


class CallbackQueryAdapter:
    def __init__(self, query: CallbackQuery) -> None:
        self._query = query
        self.data = query.data

    async def answer(self) -> None:
        await self._query.answer()


def _anchors(context: CallbackContext[Any, Any, Any, Any]) -> Anchors:
    # `build_application` seeds this; the setdefault is what lets an Application
    # assembled in a test navigate without seeding it by hand.
    anchors = context.bot_data.setdefault("anchors", Anchors())
    assert isinstance(anchors, Anchors)
    return anchors


class UpdateAdapter:
    """Bridges a real `telegram.Update` to the `UpdateLike`/`CallbackUpdateLike`
    protocols the handlers are written against, so `meal_planning_bot/handlers/*.py` never
    needs to import `telegram` (see `meal_planning_bot/handlers/__init__.py`).

    Both reply paths go through the chat's anchor (`meal_planning_bot/anchor.py`):
    a handler asks for text and never knows whether that became an edit, a new
    message, or a deletion of the command that asked for it."""

    def __init__(self, update: Update, context: CallbackContext[Any, Any, Any, Any]) -> None:
        self._update = update
        self._bot = BotAdapter(context.bot)
        self._anchors = _anchors(context)
        self.effective_user: UserLike | None = update.effective_user
        self.effective_chat: ChatLike | None = update.effective_chat
        query = update.callback_query
        self.callback_query: CallbackQueryLike | None = (
            CallbackQueryAdapter(query) if query is not None else None
        )

    def _trigger(self) -> Trigger:
        message = self._update.effective_message
        chat = self._update.effective_chat
        assert message is not None
        assert chat is not None
        is_tap = self._update.callback_query is not None
        return Trigger(
            chat_id=chat.id,
            message_id=None if is_tap else message.message_id,
            carrier_id=message.message_id if is_tap else None,
        )

    async def reply_text(self, text: str, reply_markup: Keyboard | None = None) -> None:
        await self._anchors.show(self._bot, self._trigger(), text, reply_markup)

    async def send_text(self, text: str) -> None:
        await self._anchors.send(self._bot, self._trigger(), text)


PTBCallback = Callable[[Update, CallbackContext[Any, Any, Any, Any]], Coroutine[Any, Any, None]]

# The wrapped handlers are typed against our own Protocols (UpdateLike,
# ContextLike, ...), not against `telegram`'s real types, so from PTB's point
# of view any callable shape is possible here; `Any` is the honest type.
_AnyHandler = Any


def bridge(handler: _AnyHandler) -> PTBCallback:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: CallbackContext[Any, Any, Any, Any]) -> None:
        await handler(UpdateAdapter(update, context), context)

    return wrapper


def bridge_wizard_text(handler: _AnyHandler) -> PTBCallback:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: CallbackContext[Any, Any, Any, Any]) -> None:
        message = update.effective_message
        assert message is not None
        text = message.text
        assert text is not None
        await handler(UpdateAdapter(update, context), context, text)

    return wrapper
