import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Concatenate, ParamSpec, Protocol, TypeVar

from meal_planning_bot.config import Config
from meal_planning_bot.formatting import PRIVATE_ONLY_MESSAGE

logger = logging.getLogger(__name__)


class UserLike(Protocol):
    id: int


class ChatLike(Protocol):
    id: int
    type: str


class UpdateLike(Protocol):
    effective_user: UserLike | None
    effective_chat: ChatLike | None

    async def reply_text(self, text: str) -> None: ...


U = TypeVar("U", bound=UpdateLike)
P = ParamSpec("P")

Handler = Callable[Concatenate[U, P], Awaitable[None]]


def allowed(config: Config) -> Callable[[Handler[U, P]], Handler[U, P]]:
    def decorator(handler: Handler[U, P]) -> Handler[U, P]:
        async def wrapper(update: U, /, *args: P.args, **kwargs: P.kwargs) -> None:
            user = update.effective_user
            if user is None or user.id not in config.allowed_user_ids:
                if user is not None:
                    logger.info("discarding update from disallowed user id %s", user.id)
                return
            chat = update.effective_chat
            if chat is None or not (chat.id == config.group_chat_id or chat.type == "private"):
                return
            await handler(update, *args, **kwargs)

        functools.update_wrapper(wrapper, handler)
        wrapper.__access_gated__ = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


def private_only(handler: Handler[U, P]) -> Handler[U, P]:
    async def wrapper(update: U, /, *args: P.args, **kwargs: P.kwargs) -> None:
        chat = update.effective_chat
        if chat is None or chat.type != "private":
            await update.reply_text(PRIVATE_ONLY_MESSAGE)
            return
        await handler(update, *args, **kwargs)

    functools.update_wrapper(wrapper, handler)
    return wrapper
