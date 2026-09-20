from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from telegram import CallbackQuery, Chat, Message, MessageEntity, Update, User

# Every generic parameter of `Application` is left at PTB's own default shape
# (see `meal_planning_bot/__main__.py`); this alias just keeps the six-way generic out
# of this module's signatures too.
Application = Any


@dataclass
class Sent:
    chat_id: int
    text: str
    markup: Any = None


class FakeBot:
    """A bot double with no network access. `__getattr__` raises on any method
    the code calls that this fake has not implemented deliberately, so a new
    Telegram call cannot slip through untested. `username` and `defaults` are
    plain attributes (not intercepted by `__getattr__`) because PTB's own
    internals probe them defensively with `hasattr` while building a Message's
    reply; both are always present, even unset, on a real `Bot`.
    """

    def __init__(self) -> None:
        self.username = "meal_planning_test_bot"
        self.defaults = None
        self.sent: list[Sent] = []
        self.edited: list[Sent] = []
        self.answered: list[str] = []

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def send_message(
        self, chat_id: int, text: str, reply_markup: Any = None, **kwargs: Any
    ) -> None:
        self.sent.append(Sent(chat_id, text, reply_markup))

    async def edit_message_text(
        self,
        text: str,
        chat_id: int = 0,
        message_id: int = 0,
        reply_markup: Any = None,
        **kwargs: Any,
    ) -> None:
        self.edited.append(Sent(chat_id, text, reply_markup))

    async def answer_callback_query(self, callback_query_id: str, **kwargs: Any) -> None:
        self.answered.append(callback_query_id)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"FakeBot has no {name}(); add it to the fake deliberately")


@dataclass
class Driver:
    """Feeds real `telegram.Update` objects into a real `Application` and
    exposes what the bot said. Building real `Update`/`Message`/`CallbackQuery`
    objects rather than hand-rolled fakes is deliberate: it is what exercises
    `telegram_bridge.py` and catches a handler filter or callback pattern that
    does not actually match what PTB sends it."""

    app: Application
    bot: FakeBot
    chat_id: int
    user_id: int
    chat_type: str = "private"
    _message_id: int = field(default=0)
    _update_id: int = field(default=0)

    def _next_message_id(self) -> int:
        self._message_id += 1
        return self._message_id

    def _next_update_id(self) -> int:
        self._update_id += 1
        return self._update_id

    def _chat_and_user(self) -> tuple[Chat, User]:
        return Chat(id=self.chat_id, type=self.chat_type), User(
            id=self.user_id, first_name="Tester", is_bot=False
        )

    async def send(self, text: str) -> str:
        chat, user = self._chat_and_user()
        entities = ()
        if text.startswith("/"):
            command_token = text.split(maxsplit=1)[0]
            entities = (
                MessageEntity(
                    type=MessageEntity.BOT_COMMAND, offset=0, length=len(command_token)
                ),
            )
        message = Message(
            message_id=self._next_message_id(),
            date=datetime.now(UTC),
            chat=chat,
            from_user=user,
            text=text,
            entities=entities,
        )
        message.set_bot(self.bot)
        update = Update(update_id=self._next_update_id(), message=message)
        await self.app.process_update(update)
        return self.last

    async def tap(self, callback_data: str) -> str:
        chat, user = self._chat_and_user()
        message = Message(
            message_id=self._next_message_id(),
            date=datetime.now(UTC),
            chat=chat,
            from_user=user,
        )
        message.set_bot(self.bot)
        query = CallbackQuery(
            id=str(self._next_message_id()),
            from_user=user,
            chat_instance="1",
            data=callback_data,
            message=message,
        )
        query.set_bot(self.bot)
        update = Update(update_id=self._next_update_id(), callback_query=query)
        await self.app.process_update(update)
        return self.last

    @property
    def last(self) -> str:
        # Empty when the caller is outside the allow-list: no reply was ever
        # sent, and the disallowed-user test still needs `.send`/`.tap` to
        # return without raising.
        if self.bot.sent:
            return self.bot.sent[-1].text
        if self.bot.edited:
            return self.bot.edited[-1].text
        return ""
