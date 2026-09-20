import functools
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from meal_planning_bot.handlers import CallbackQueryLike, ChatLike, Keyboard, UserLike


def to_markup(keyboard: Keyboard | None) -> InlineKeyboardMarkup | None:
    if keyboard is None:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=data) for label, data in row]
            for row in keyboard
        ]
    )


class CallbackQueryAdapter:
    def __init__(self, query: CallbackQuery) -> None:
        self._query = query
        self.data = query.data

    async def answer(self) -> None:
        await self._query.answer()

    async def edit_message_text(self, text: str, reply_markup: Keyboard | None = None) -> None:
        await self._query.edit_message_text(text, reply_markup=to_markup(reply_markup))


class UpdateAdapter:
    """Bridges a real `telegram.Update` to the `UpdateLike`/`CallbackUpdateLike`
    protocols the handlers are written against, so `meal_planning_bot/handlers/*.py` never
    needs to import `telegram` (see `meal_planning_bot/handlers/__init__.py`)."""

    def __init__(self, update: Update) -> None:
        self._update = update
        self.effective_user: UserLike | None = update.effective_user
        self.effective_chat: ChatLike | None = update.effective_chat
        query = update.callback_query
        self.callback_query: CallbackQueryLike | None = (
            CallbackQueryAdapter(query) if query is not None else None
        )

    async def reply_text(self, text: str, reply_markup: Keyboard | None = None) -> None:
        message = self._update.effective_message
        assert message is not None
        await message.reply_text(text, reply_markup=to_markup(reply_markup))


PTBCallback = Callable[[Update, CallbackContext[Any, Any, Any, Any]], Coroutine[Any, Any, None]]

# The wrapped handlers are typed against our own Protocols (UpdateLike,
# ContextLike, ...), not against `telegram`'s real types, so from PTB's point
# of view any callable shape is possible here; `Any` is the honest type.
_AnyHandler = Any


def bridge(handler: _AnyHandler) -> PTBCallback:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: CallbackContext[Any, Any, Any, Any]) -> None:
        await handler(UpdateAdapter(update), context)

    return wrapper


def bridge_wizard_text(handler: _AnyHandler) -> PTBCallback:
    @functools.wraps(handler)
    async def wrapper(update: Update, context: CallbackContext[Any, Any, Any, Any]) -> None:
        message = update.effective_message
        assert message is not None
        text = message.text
        assert text is not None
        await handler(UpdateAdapter(update), context, text)

    return wrapper
