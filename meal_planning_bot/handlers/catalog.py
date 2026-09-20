from dataclasses import dataclass
from math import ceil
from sqlite3 import Connection

from meal_planning_bot import repo
from meal_planning_bot.access import private_only
from meal_planning_bot.formatting import (
    DISH_FUZZY_PROMPT,
    DISH_NOT_FOUND_MESSAGE,
    DISHES_PAGE_SIZE,
    FOOD_NOT_FOUND_MESSAGE,
    PAGINATION_NEXT_BUTTON,
    PAGINATION_PREV_BUTTON,
    RESTORE_AMBIGUOUS_PROMPT,
    RESTORE_NOT_FOUND_MESSAGE,
    render_dish,
    render_dishes_page,
    render_foods_page,
    render_restored_dish,
    render_restored_food,
)
from meal_planning_bot.handlers import (
    ButtonRow,
    CallbackUpdateLike,
    ContextLike,
    Keyboard,
    UpdateLike,
    get_conn,
    load_all_foods,
)
from meal_planning_bot.models import CATEGORY_ORDER, Dish, Food, MealType

_ARCHIVED_KEYWORD = "archivados"
_RESTORE_BUTTON_LIMIT = 5
_DISH_SEARCH_LIMIT = 1000


@dataclass(frozen=True)
class DishesPageCallback:
    page: int
    archived: bool


@dataclass(frozen=True)
class FoodsPageCallback:
    page: int
    archived: bool


@dataclass(frozen=True)
class DishCallback:
    dish_id: int


@dataclass(frozen=True)
class RestoreCallback:
    kind: str
    item_id: int


CallbackAction = DishesPageCallback | FoodsPageCallback | DishCallback | RestoreCallback


def parse_callback(data: str) -> CallbackAction | None:
    parts = data.split(":")
    if len(parts) == 3 and parts[0] in ("dishes", "foods") and parts[2] in ("0", "1"):
        try:
            page = int(parts[1])
        except ValueError:
            return None
        archived = parts[2] == "1"
        if parts[0] == "dishes":
            return DishesPageCallback(page=page, archived=archived)
        return FoodsPageCallback(page=page, archived=archived)
    if len(parts) == 2 and parts[0] == "dish":
        try:
            dish_id = int(parts[1])
        except ValueError:
            return None
        return DishCallback(dish_id=dish_id)
    if len(parts) == 3 and parts[0] == "restore" and parts[1] in ("dish", "food"):
        try:
            item_id = int(parts[2])
        except ValueError:
            return None
        return RestoreCallback(kind=parts[1], item_id=item_id)
    return None


_MEAL_TYPE_ORDER: tuple[MealType, ...] = tuple(MealType)


def _sorted_dishes(conn: Connection, archived: bool) -> list[Dish]:
    dishes = repo.list_dishes(conn, archived=archived)
    return sorted(
        dishes, key=lambda d: (_MEAL_TYPE_ORDER.index(d.meal_type), d.name.lower())
    )


def _sorted_foods(conn: Connection, archived: bool) -> list[Food]:
    foods = repo.list_foods(conn, archived=archived)
    return sorted(foods, key=lambda f: (CATEGORY_ORDER.index(f.category), f.name.lower()))


def _page_keyboard(prefix: str, page: int, archived: bool, total: int) -> Keyboard | None:
    total_pages = max(1, ceil(total / DISHES_PAGE_SIZE))
    buttons: list[tuple[str, str]] = []
    if page > 1:
        buttons.append((PAGINATION_PREV_BUTTON, f"{prefix}:{page - 1}:{int(archived)}"))
    if page < total_pages:
        buttons.append((PAGINATION_NEXT_BUTTON, f"{prefix}:{page + 1}:{int(archived)}"))
    if not buttons:
        return None
    row: ButtonRow = tuple(buttons)
    return (row,)


async def cmd_dishes(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    archived = bool(context.args) and context.args[0].lower() == _ARCHIVED_KEYWORD
    dishes = _sorted_dishes(conn, archived)
    text = render_dishes_page(dishes, page=1)
    keyboard = _page_keyboard("dishes", 1, archived, len(dishes))
    await update.reply_text(text, reply_markup=keyboard)


async def cmd_dish(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    name = " ".join(context.args).strip()
    if not name:
        await update.reply_text(DISH_NOT_FOUND_MESSAGE)
        return

    matches = repo.find_dishes_by_name(conn, name, limit=_DISH_SEARCH_LIMIT)
    exact = next((d for d in matches if d.name.lower() == name.lower()), None)
    if exact is not None:
        foods = load_all_foods(conn)
        await update.reply_text(render_dish(exact, foods))
        return

    if not matches:
        await update.reply_text(DISH_NOT_FOUND_MESSAGE)
        return

    row: ButtonRow = tuple((d.name, f"dish:{d.id}") for d in matches[:5])
    await update.reply_text(DISH_FUZZY_PROMPT, reply_markup=(row,))


async def cmd_foods(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    archived = bool(context.args) and context.args[0].lower() == _ARCHIVED_KEYWORD
    foods = _sorted_foods(conn, archived)
    keyboard = _page_keyboard("foods", 1, archived, len(foods))
    await update.reply_text(render_foods_page(foods, page=1), reply_markup=keyboard)


async def _cmd_restore(update: UpdateLike, context: ContextLike) -> None:
    conn = get_conn(context)
    name = " ".join(context.args).strip().lower()
    if not name:
        await update.reply_text(RESTORE_NOT_FOUND_MESSAGE)
        return

    dish_matches = [d for d in repo.list_dishes(conn, archived=True) if name in d.name.lower()]
    food_matches = [f for f in repo.list_foods(conn, archived=True) if name in f.name.lower()]
    exact_dish = next((d for d in dish_matches if d.name.lower() == name), None)
    exact_food = next((f for f in food_matches if f.name.lower() == name), None)

    if exact_dish is not None and exact_food is None:
        restored = repo.reactivate_dish(conn, exact_dish.id)
        await update.reply_text(render_restored_dish(restored))
        return
    if exact_food is not None and exact_dish is None:
        restored_food = repo.reactivate_food(conn, exact_food.id)
        await update.reply_text(render_restored_food(restored_food))
        return

    total = len(dish_matches) + len(food_matches)
    if total == 0:
        await update.reply_text(RESTORE_NOT_FOUND_MESSAGE)
        return
    if total == 1:
        if dish_matches:
            restored = repo.reactivate_dish(conn, dish_matches[0].id)
            await update.reply_text(render_restored_dish(restored))
        else:
            restored_food = repo.reactivate_food(conn, food_matches[0].id)
            await update.reply_text(render_restored_food(restored_food))
        return

    dish_buttons = tuple(
        (d.name, f"restore:dish:{d.id}") for d in dish_matches[:_RESTORE_BUTTON_LIMIT]
    )
    remaining = max(0, _RESTORE_BUTTON_LIMIT - len(dish_buttons))
    food_buttons = tuple(
        (f.name, f"restore:food:{f.id}") for f in food_matches[:remaining]
    )
    row: ButtonRow = dish_buttons + food_buttons
    await update.reply_text(RESTORE_AMBIGUOUS_PROMPT, reply_markup=(row,))


cmd_restore = private_only(_cmd_restore)


async def on_catalog_callback(update: CallbackUpdateLike, context: ContextLike) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    action = parse_callback(query.data)
    if action is None:
        await query.answer()
        return

    conn = get_conn(context)
    await query.answer()

    if isinstance(action, DishesPageCallback):
        dishes = _sorted_dishes(conn, action.archived)
        text = render_dishes_page(dishes, page=action.page)
        keyboard = _page_keyboard("dishes", action.page, action.archived, len(dishes))
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    if isinstance(action, FoodsPageCallback):
        page_foods = _sorted_foods(conn, action.archived)
        text = render_foods_page(page_foods, page=action.page)
        keyboard = _page_keyboard("foods", action.page, action.archived, len(page_foods))
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    if isinstance(action, DishCallback):
        try:
            dish = repo.get_dish(conn, action.dish_id)
        except LookupError:
            await query.edit_message_text(DISH_NOT_FOUND_MESSAGE)
            return
        foods = load_all_foods(conn)
        await query.edit_message_text(render_dish(dish, foods))
        return

    if action.kind == "dish":
        try:
            restored_dish = repo.reactivate_dish(conn, action.item_id)
        except LookupError:
            await query.edit_message_text(RESTORE_NOT_FOUND_MESSAGE)
            return
        await query.edit_message_text(render_restored_dish(restored_dish))
        return

    try:
        restored_food = repo.reactivate_food(conn, action.item_id)
    except LookupError:
        await query.edit_message_text(FOOD_NOT_FOUND_MESSAGE)
        return
    await query.edit_message_text(render_restored_food(restored_food))
