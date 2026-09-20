from collections.abc import Callable, MutableMapping, Sequence
from datetime import date
from random import Random
from sqlite3 import Connection
from typing import Protocol, cast

from meal_planning_bot import repo
from meal_planning_bot.models import Dish, Food, Plan


class UserLike(Protocol):
    id: int


class ChatLike(Protocol):
    id: int
    type: str


# A button is (label, callback_data); a row is buttons shown side by side; a
# keyboard is the rows stacked top to bottom. Real python-telegram-bot markup
# is assembled from this shape at registration time (Task 20) so this module
# stays free of the telegram import, matching access.py.
ButtonRow = tuple[tuple[str, str], ...]
Keyboard = tuple[ButtonRow, ...]


class UpdateLike(Protocol):
    effective_user: UserLike | None
    effective_chat: ChatLike | None

    async def reply_text(self, text: str, reply_markup: Keyboard | None = None) -> None: ...


class CallbackQueryLike(Protocol):
    data: str | None

    async def answer(self) -> None: ...
    async def edit_message_text(self, text: str, reply_markup: Keyboard | None = None) -> None: ...


class CallbackUpdateLike(UpdateLike, Protocol):
    callback_query: CallbackQueryLike | None


class ContextLike(Protocol):
    args: Sequence[str]
    bot_data: MutableMapping[str, object]


def get_conn(context: ContextLike) -> Connection:
    conn = context.bot_data["conn"]
    assert isinstance(conn, Connection)
    return conn


def get_clock(context: ContextLike) -> Callable[[], date]:
    return cast(Callable[[], date], context.bot_data["clock"])


def get_rng(context: ContextLike) -> Random:
    rng = context.bot_data["rng"]
    assert isinstance(rng, Random)
    return rng


def load_dishes_for_plan(conn: Connection, plan: Plan) -> dict[int, Dish]:
    dish_ids = {entry.dish_id for entry in plan.entries}
    return {dish_id: repo.get_dish(conn, dish_id) for dish_id in dish_ids}


def load_all_foods(conn: Connection) -> dict[int, Food]:
    foods = repo.list_foods(conn, archived=False) + repo.list_foods(conn, archived=True)
    return {food.id: food for food in foods}
