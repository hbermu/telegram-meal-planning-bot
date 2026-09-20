import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import TypeVar, cast

from meal_planning_bot import repo
from meal_planning_bot.formatting import (
    DELETE_CANCELLED_MESSAGE,
    DISH_DISCARDED_MESSAGE,
    DISH_NAME_DUPLICATE_MESSAGE,
    FOOD_AMBIGUOUS_PROMPT,
    FOOD_DISCARDED_MESSAGE,
    INGREDIENT_FORMAT_ERROR_MESSAGE,
    INGREDIENT_QUANTITY_ERROR_MESSAGE,
    NO_WIZARD_IN_PROGRESS_MESSAGE,
    WIZARD_CANCELLED_MESSAGE,
    WIZARD_REPLACED_NOTICE,
)
from meal_planning_bot.handlers.wizards import (
    cmd_cancel,
    cmd_deletedish,
    cmd_deletefood,
    cmd_editdish,
    cmd_editfood,
    cmd_newdish,
    cmd_newfood,
    on_wizard_callback,
    on_wizard_message,
)
from meal_planning_bot.models import Category, DishIngredient, MealType, Unit
from tests.test_handlers import FakeCallbackQuery, FakeContext, FakeUpdate, _context, _update

_COMMANDS: dict[str, Callable[[FakeUpdate, FakeContext], Awaitable[None]]] = {
    "newdish": cmd_newdish,
    "editdish": cmd_editdish,
    "deletedish": cmd_deletedish,
    "newfood": cmd_newfood,
    "editfood": cmd_editfood,
    "deletefood": cmd_deletefood,
    "cancel": cmd_cancel,
}


@dataclass
class Wizard:
    context: FakeContext
    update: FakeUpdate

    async def send(self, text: str) -> FakeUpdate:
        self.update = _update()
        if text.startswith("/"):
            name = text[1:].split()[0]
            await _COMMANDS[name](self.update, self.context)
        else:
            await on_wizard_message(self.update, self.context, text)
        return self.update

    async def tap(self, data: str) -> FakeUpdate:
        query = FakeCallbackQuery(data=data)
        self.update = _update(callback_query=query)
        await on_wizard_callback(self.update, self.context)
        return self.update


def _wizard(conn: sqlite3.Connection, today: date = date(2026, 9, 21)) -> Wizard:
    context = _context(conn, today)
    return Wizard(context=context, update=_update())


_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    return asyncio.run(coro)


def _dish_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM dishes").fetchone()
    return int(row[0])


def _food_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM foods").fetchone()
    return int(row[0])


def _last(update: FakeUpdate) -> str:
    return update.replies[-1]


# --- /newdish happy path, writes only on confirm ----------------------------


async def _newdish_with_existing_food(w: Wizard) -> None:
    conn = cast(sqlite3.Connection, w.context.bot_data["conn"])
    repo.create_food(conn, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    await w.send("/newdish")
    await w.send("Arroz con pollo")
    await w.tap("meal:lunch")
    await w.send("arroz 200")
    await w.tap("ing:done")
    await w.tap("steps:skip")
    await w.tap("kcal:accept")


def test_newdish_writes_only_on_confirm(conn: sqlite3.Connection) -> None:
    w = _wizard(conn)
    _run(_newdish_with_existing_food(w))
    assert _dish_count(conn) == 0

    _run(w.tap("confirm:yes"))
    assert _dish_count(conn) == 1
    dish = repo.list_dishes(conn)[0]
    assert dish.name == "Arroz con pollo"
    assert dish.meal_type is MealType.LUNCH
    assert dish.kcal_override is None
    assert dish.kcal == 260  # 200g @ 130 kcal/100g


def test_newdish_discard_at_confirm_writes_nothing(conn: sqlite3.Connection) -> None:
    w = _wizard(conn)
    _run(_newdish_with_existing_food(w))
    _run(w.tap("confirm:no"))
    assert _last(w.update) == DISH_DISCARDED_MESSAGE
    assert _dish_count(conn) == 0
    _run(w.send("/cancel"))
    assert _last(w.update) == NO_WIZARD_IN_PROGRESS_MESSAGE


# --- inline food creation, with and without a seed match -------------------


def test_newdish_inline_food_creation_prefills_from_seed(conn: sqlite3.Connection) -> None:
    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("Pollo al horno"))
    _run(w.tap("meal:lunch"))

    _run(w.send("pollo 200"))
    assert "sugerido: g" in _last(w.update)
    _run(w.tap("unit:g"))
    assert "sugerido: Carne y pescado" in _last(w.update)
    _run(w.tap("cat:meat_fish"))
    assert "sugerido: 165" in _last(w.update)
    assert w.update.markups[-1] is not None  # the "use the suggestion" button

    _run(w.tap("kcalref:accept"))
    _run(w.tap("ing:done"))
    _run(w.tap("steps:skip"))
    _run(w.tap("kcal:accept"))

    assert _dish_count(conn) == 0
    assert _food_count(conn) == 0

    _run(w.tap("confirm:yes"))
    assert _dish_count(conn) == 1
    assert _food_count(conn) == 1
    food = repo.get_food_by_exact_name(conn, "pollo")
    assert food is not None
    assert food.unit is Unit.G
    assert food.category is Category.MEAT_FISH
    assert food.kcal_ref == 165


def test_newdish_inline_food_creation_with_no_seed_match_has_no_default(
    conn: sqlite3.Connection,
) -> None:
    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("Plato raro"))
    _run(w.tap("meal:lunch"))

    _run(w.send("alienfood123 50"))
    assert "sugerido" not in _last(w.update)
    _run(w.tap("unit:ml"))
    assert "sugerido" not in _last(w.update)
    _run(w.tap("cat:other"))
    assert "sugerido" not in _last(w.update)
    assert w.update.markups[-1] is None  # no accept-suggestion button when there is no seed

    _run(w.send("42"))
    _run(w.tap("ing:done"))
    _run(w.tap("steps:skip"))
    _run(w.tap("kcal:accept"))
    _run(w.tap("confirm:yes"))

    food = repo.get_food_by_exact_name(conn, "alienfood123")
    assert food is not None
    assert food.unit is Unit.ML
    assert food.category is Category.OTHER
    assert food.kcal_ref == 42


# --- ambiguous food name -----------------------------------------------


def test_ambiguous_food_name_offers_up_to_five_buttons(conn: sqlite3.Connection) -> None:
    for i in range(3):
        repo.create_food(
            conn,
            name=f"Pollo variante {i}",
            unit=Unit.G,
            category=Category.MEAT_FISH,
            kcal_ref=100.0,
        )
    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("Plato de pollo"))
    _run(w.tap("meal:lunch"))

    _run(w.send("pollo 100"))
    assert _last(w.update) == FOOD_AMBIGUOUS_PROMPT
    keyboard = w.update.markups[-1]
    assert keyboard is not None
    assert len(keyboard[0]) == 3
    _label, callback_data = keyboard[0][0]

    _run(w.tap(callback_data))
    _run(w.tap("ing:done"))
    _run(w.tap("steps:skip"))
    _run(w.tap("kcal:accept"))
    _run(w.tap("confirm:yes"))
    assert _dish_count(conn) == 1
    assert _food_count(conn) == 3  # nothing new was created


# --- invalid quantity re-asks the same step ---------------------------------


def test_invalid_quantity_reasks_same_step(conn: sqlite3.Connection) -> None:
    repo.create_food(conn, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("Arroz solo"))
    _run(w.tap("meal:lunch"))

    _run(w.send("arroz abc"))
    assert _last(w.update) == INGREDIENT_QUANTITY_ERROR_MESSAGE
    _run(w.send("arroz -5"))
    assert _last(w.update) == INGREDIENT_QUANTITY_ERROR_MESSAGE
    _run(w.send("arroz 0"))
    assert _last(w.update) == INGREDIENT_QUANTITY_ERROR_MESSAGE
    _run(w.send("justonetoken"))
    assert _last(w.update) == INGREDIENT_FORMAT_ERROR_MESSAGE

    # the step is still waiting for a valid ingredient, unaffected by the retries
    _run(w.send("arroz 200"))
    _run(w.tap("ing:done"))
    _run(w.tap("steps:skip"))
    _run(w.tap("kcal:accept"))
    _run(w.tap("confirm:yes"))
    assert _dish_count(conn) == 1


# --- /cancel and a second wizard replacing the first ------------------------


def test_cancel_discards_the_wizard_and_writes_nothing(conn: sqlite3.Connection) -> None:
    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("A medio hacer"))
    _run(w.send("/cancel"))
    assert _last(w.update) == WIZARD_CANCELLED_MESSAGE
    assert _dish_count(conn) == 0

    _run(w.send("/cancel"))
    assert _last(w.update) == NO_WIZARD_IN_PROGRESS_MESSAGE


def test_starting_a_second_wizard_replaces_the_first_with_a_notice(
    conn: sqlite3.Connection,
) -> None:
    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("/newfood"))
    assert WIZARD_REPLACED_NOTICE in w.update.replies
    assert _dish_count(conn) == 0
    assert _food_count(conn) == 0


# --- calories: computed vs. overridden --------------------------------------


def test_kcal_step_accept_stores_no_override_and_typed_value_stores_one(
    conn: sqlite3.Connection,
) -> None:
    repo.create_food(conn, name="Base", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0)

    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("Computado"))
    _run(w.tap("meal:lunch"))
    _run(w.send("base 200"))
    _run(w.tap("ing:done"))
    _run(w.tap("steps:skip"))
    assert "200 kcal" in _last(w.update)
    _run(w.tap("kcal:accept"))
    _run(w.tap("confirm:yes"))
    computed_dish = repo.get_dish(conn, repo.list_dishes(conn)[0].id)
    assert computed_dish.kcal_override is None
    assert computed_dish.kcal == 200

    w2 = _wizard(conn)
    _run(w2.send("/newdish"))
    _run(w2.send("Fijado"))
    _run(w2.tap("meal:lunch"))
    _run(w2.send("base 200"))
    _run(w2.tap("ing:done"))
    _run(w2.tap("steps:skip"))
    _run(w2.send("999"))
    _run(w2.tap("confirm:yes"))
    overridden_dish = next(d for d in repo.list_dishes(conn) if d.name == "Fijado")
    assert overridden_dish.kcal_override == 999
    assert overridden_dish.kcal == 999


# --- the confirmation write is one transaction ------------------------------


def test_confirmation_write_is_one_transaction(conn: sqlite3.Connection) -> None:
    existing_food_id = repo.create_food(
        conn, name="Relleno", unit=Unit.G, category=Category.PANTRY, kcal_ref=50.0
    ).id
    repo.create_dish(
        conn,
        name="Duplicado",
        meal_type=MealType.DINNER,
        ingredients=[DishIngredient(food_id=existing_food_id, quantity=100.0)],
    )
    assert _dish_count(conn) == 1

    w = _wizard(conn)
    _run(w.send("/newdish"))
    _run(w.send("Duplicado"))  # same name as the dish that already exists
    _run(w.tap("meal:lunch"))
    _run(w.send("uniqueingredientxyz 10"))
    _run(w.tap("unit:g"))
    _run(w.tap("cat:other"))
    _run(w.send("7"))
    _run(w.tap("ing:done"))
    _run(w.tap("steps:skip"))
    _run(w.tap("kcal:accept"))

    _run(w.tap("confirm:yes"))

    assert _last(w.update) == DISH_NAME_DUPLICATE_MESSAGE
    # the dish insert failed on the UNIQUE constraint; the food insert that
    # happened earlier in the same transaction must have been rolled back too
    assert _dish_count(conn) == 1
    assert repo.get_food_by_exact_name(conn, "uniqueingredientxyz") is None


# --- /editdish changes exactly one field ------------------------------------


def test_editdish_changes_only_the_chosen_field(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Base", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )
    original = repo.create_dish(
        conn,
        name="Original",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
        steps="Paso 1.",
    )

    w = _wizard(conn)
    _run(w.send("/editdish"))
    _run(w.send("Original"))
    _run(w.tap("field:name"))
    _run(w.send("Renombrado"))
    _run(w.tap("confirm:yes"))

    updated = repo.get_dish(conn, original.id)
    assert updated.name == "Renombrado"
    assert updated.meal_type is MealType.LUNCH
    assert updated.steps == "Paso 1."
    assert updated.ingredients == original.ingredients


def test_editdish_with_ambiguous_name_offers_buttons(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Base", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )
    for i in range(2):
        repo.create_dish(
            conn,
            name=f"Sopa {i}",
            meal_type=MealType.DINNER,
            ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
        )

    w = _wizard(conn)
    _run(w.send("/editdish"))
    _run(w.send("Sopa"))
    keyboard = w.update.markups[-1]
    assert keyboard is not None
    assert len(keyboard[0]) == 2


# --- /deletedish and /deletefood require confirmation -----------------------


def test_deletedish_requires_confirmation(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Base", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )
    dish = repo.create_dish(
        conn,
        name="A archivar",
        meal_type=MealType.DINNER,
        ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
    )

    w = _wizard(conn)
    _run(w.send("/deletedish"))
    _run(w.send("A archivar"))
    _run(w.tap("deletedish:no"))
    assert _last(w.update) == DELETE_CANCELLED_MESSAGE
    assert repo.get_dish(conn, dish.id).active

    w2 = _wizard(conn)
    _run(w2.send("/deletedish"))
    _run(w2.send("A archivar"))
    _run(w2.tap("deletedish:yes"))
    assert not repo.get_dish(conn, dish.id).active


def test_deletefood_requires_confirmation_and_respects_food_in_use(
    conn: sqlite3.Connection,
) -> None:
    used_food = repo.create_food(
        conn, name="Usado", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )
    repo.create_dish(
        conn,
        name="Lo usa",
        meal_type=MealType.DINNER,
        ingredients=[DishIngredient(food_id=used_food.id, quantity=100.0)],
    )
    free_food = repo.create_food(
        conn, name="Libre", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )

    w = _wizard(conn)
    _run(w.send("/deletefood"))
    _run(w.send("Usado"))
    _run(w.tap("deletefood:yes"))
    still_used = repo.get_food_by_exact_name(conn, "Usado")
    assert still_used is not None
    assert still_used.active

    w2 = _wizard(conn)
    _run(w2.send("/deletefood"))
    _run(w2.send("Libre"))
    _run(w2.tap("deletefood:yes"))
    now_archived = repo.get_food_by_exact_name(conn, "Libre")
    assert now_archived is not None
    assert not now_archived.active
    assert free_food.id != used_food.id


# --- /newfood and /editfood ---------------------------------------------


def test_newfood_creates_a_food(conn: sqlite3.Connection) -> None:
    w = _wizard(conn)
    _run(w.send("/newfood"))
    _run(w.send("Yogur"))
    _run(w.tap("unit:unit"))
    _run(w.tap("cat:dairy_eggs"))
    _run(w.send("120"))
    assert _food_count(conn) == 0
    _run(w.tap("confirm:yes"))
    food = repo.get_food_by_exact_name(conn, "Yogur")
    assert food is not None
    assert food.unit is Unit.UNIT
    assert food.category is Category.DAIRY_EGGS
    assert food.kcal_ref == 120


def test_editfood_changing_unit_also_asks_for_a_new_kcal_ref(conn: sqlite3.Connection) -> None:
    repo.create_food(conn, name="Leche", unit=Unit.ML, category=Category.DAIRY_EGGS, kcal_ref=42.0)

    w = _wizard(conn)
    _run(w.send("/editfood"))
    _run(w.send("Leche"))
    _run(w.tap("ffield:unit"))
    _run(w.tap("unit:g"))
    _run(w.send("45"))
    _run(w.tap("confirm:yes"))

    updated = repo.get_food_by_exact_name(conn, "Leche")
    assert updated is not None
    assert updated.unit is Unit.G
    assert updated.kcal_ref == 45


def test_newfood_discard_at_confirm_writes_nothing(conn: sqlite3.Connection) -> None:
    w = _wizard(conn)
    _run(w.send("/newfood"))
    _run(w.send("Descartado"))
    _run(w.tap("unit:g"))
    _run(w.tap("cat:other"))
    _run(w.send("10"))
    _run(w.tap("confirm:no"))
    assert _last(w.update) == FOOD_DISCARDED_MESSAGE
    assert repo.get_food_by_exact_name(conn, "Descartado") is None
