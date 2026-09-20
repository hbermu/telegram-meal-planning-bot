import asyncio
import logging
import random
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from telegram.ext import ExtBot

from meal_planning_bot import repo
from meal_planning_bot.__main__ import _configure_logging, build_application
from meal_planning_bot.config import Config
from meal_planning_bot.formatting import (
    COMMANDS,
    DISH_FUZZY_PROMPT,
    DISH_NOT_FOUND_MESSAGE,
    NO_PLAN_MESSAGE,
    PAGINATION_NEXT_BUTTON,
    RESTORE_AMBIGUOUS_PROMPT,
    RESTORE_NOT_FOUND_MESSAGE,
    SWAP_USAGE_MESSAGE,
    WEEKEND_MESSAGE,
    render_help,
    render_my_id,
    render_relaxation_notice,
    render_restored_dish,
    render_restored_food,
    render_swap_unsatisfiable,
)
from meal_planning_bot.handlers.catalog import (
    DishCallback,
    DishesPageCallback,
    RestoreCallback,
    cmd_dish,
    cmd_dishes,
    cmd_foods,
    cmd_restore,
    on_catalog_callback,
    parse_callback,
)
from meal_planning_bot.handlers.help import cmd_help, cmd_myid, cmd_start, cmd_unknown
from meal_planning_bot.handlers.plan import (
    cmd_plan,
    cmd_regenerate,
    cmd_shopping,
    cmd_swap,
    cmd_today,
    parse_swap_args,
)
from meal_planning_bot.models import Category, DishIngredient, MealType, Plan, Slot, Unit
from meal_planning_bot.planner import plan_week
from meal_planning_bot.repo import planner_settings
from meal_planning_bot.weeks import ArgumentError


@dataclass
class FakeChat:
    id: int
    type: str = "private"


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeCallbackQuery:
    data: str | None
    answered: bool = False
    edits: list[str] = field(default_factory=list)
    edit_markups: list[Any] = field(default_factory=list)

    async def answer(self) -> None:
        self.answered = True

    async def edit_message_text(self, text: str, reply_markup: Any = None) -> None:
        self.edits.append(text)
        self.edit_markups.append(reply_markup)


@dataclass
class FakeUpdate:
    effective_user: FakeUser | None
    effective_chat: FakeChat | None
    callback_query: FakeCallbackQuery | None = None
    replies: list[str] = field(default_factory=list)
    markups: list[Any] = field(default_factory=list)

    async def reply_text(self, text: str, reply_markup: Any = None) -> None:
        self.replies.append(text)
        self.markups.append(reply_markup)


@dataclass
class FakeContext:
    args: list[str]
    bot_data: dict[str, object]
    user_data: dict[str, object] = field(default_factory=dict)


def _context(
    conn: sqlite3.Connection, today: date, args: list[str] | None = None, seed: int = 42
) -> FakeContext:
    return FakeContext(
        args=args or [],
        bot_data={"conn": conn, "clock": lambda: today, "rng": random.Random(seed)},
    )


def _update(
    chat_id: int = 1,
    user_id: int = 1,
    chat_type: str = "private",
    callback_query: FakeCallbackQuery | None = None,
) -> FakeUpdate:
    return FakeUpdate(
        effective_user=FakeUser(user_id),
        effective_chat=FakeChat(chat_id, chat_type),
        callback_query=callback_query,
    )


def _run(coro: Any) -> None:
    asyncio.run(coro)


def _seed_food(conn: sqlite3.Connection, name: str = "Arroz") -> int:
    food = repo.create_food(conn, name=name, unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    return food.id


def _seed_full_catalogue(conn: sqlite3.Connection) -> None:
    # Every dish gets its own food so max_food_repeats_per_day (2) is never
    # tripped by five slots a day all sharing one ingredient.
    counts = {MealType.BREAKFAST: 6, MealType.SNACK: 12, MealType.LUNCH: 6, MealType.DINNER: 6}
    for meal_type, count in counts.items():
        for i in range(count):
            food_id = _seed_food(conn, name=f"{meal_type.value}-food-{i}")
            repo.create_dish(
                conn,
                name=f"{meal_type.value}-{i}",
                meal_type=meal_type,
                ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
                kcal_override=400,
            )


def _seed_plan(conn: sqlite3.Connection, week_start: date) -> None:
    _seed_full_catalogue(conn)
    catalogue = repo.list_dishes(conn, archived=False)
    plan = plan_week(catalogue, [], planner_settings(conn), week_start, random.Random(1))
    repo.save_plan(conn, plan)


# --- /start, /help, /myid ---------------------------------------------------


def test_start_and_help_return_the_command_list(conn: sqlite3.Connection) -> None:
    for handler in (cmd_start, cmd_help):
        update = _update()
        _run(handler(update, _context(conn, date(2026, 9, 21))))
        assert update.replies == [render_help()]


def test_unknown_command_falls_back_to_help(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_unknown(update, _context(conn, date(2026, 9, 21))))
    assert update.replies == [render_help()]


def test_myid_works_for_anyone_in_a_private_chat(conn: sqlite3.Connection) -> None:
    update = _update(user_id=999, chat_type="private")
    _run(cmd_myid(update, _context(conn, date(2026, 9, 21))))
    assert update.replies == [render_my_id(999)]


def test_myid_refuses_the_group_chat(conn: sqlite3.Connection) -> None:
    update = _update(chat_id=-1001, chat_type="group")
    _run(cmd_myid(update, _context(conn, date(2026, 9, 21))))
    assert update.replies == ["Ese comando solo funciona en un chat privado conmigo."]


# --- /plan -------------------------------------------------------------


def test_plan_with_no_stored_plan_suggests_regenerate(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_plan(update, _context(conn, date(2026, 9, 21))))
    assert update.replies == [NO_PLAN_MESSAGE]


def test_plan_renders_the_stored_week(conn: sqlite3.Connection) -> None:
    week_start = date(2026, 9, 21)
    _seed_plan(conn, week_start)
    update = _update()
    _run(cmd_plan(update, _context(conn, week_start)))
    assert len(update.replies) == 1
    assert "Lunes" in update.replies[0]
    assert "Plan de esta semana" in update.replies[0]


def test_plan_siguiente_shows_next_week_and_leaves_current_reply_different(
    conn: sqlite3.Connection,
) -> None:
    current_start = date(2026, 9, 21)
    next_start = date(2026, 9, 28)
    _seed_full_catalogue(conn)
    catalogue = repo.list_dishes(conn, archived=False)
    settings = planner_settings(conn)
    repo.save_plan(conn, plan_week(catalogue, [], settings, current_start, random.Random(2)))
    repo.save_plan(conn, plan_week(catalogue, [], settings, next_start, random.Random(4)))

    current_update = _update()
    _run(cmd_plan(current_update, _context(conn, current_start)))
    next_update = _update()
    _run(cmd_plan(next_update, _context(conn, current_start, ["siguiente"])))

    assert "Plan de esta semana" in current_update.replies[0]
    assert "Plan de la semana que viene" in next_update.replies[0]
    assert "28/09" in next_update.replies[0]
    assert current_update.replies[0] != next_update.replies[0]


def test_plan_rejects_unparseable_argument(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_plan(update, _context(conn, date(2026, 9, 21), ["martes"])))
    assert update.replies == ["No entendí ese argumento."]


# --- /today --------------------------------------------------------------


def test_today_on_saturday_says_the_weekend_is_not_planned(conn: sqlite3.Connection) -> None:
    saturday = date(2026, 9, 26)
    update = _update()
    _run(cmd_today(update, _context(conn, saturday)))
    assert update.replies == [WEEKEND_MESSAGE]


def test_today_on_sunday_says_the_weekend_is_not_planned(conn: sqlite3.Connection) -> None:
    sunday = date(2026, 9, 27)
    update = _update()
    _run(cmd_today(update, _context(conn, sunday)))
    assert update.replies == [WEEKEND_MESSAGE]


def test_today_on_a_weekday_with_no_plan_suggests_regenerate(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    update = _update()
    _run(cmd_today(update, _context(conn, monday)))
    assert update.replies == [NO_PLAN_MESSAGE]


def test_today_on_a_weekday_with_a_plan_shows_only_that_day(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    update = _update()
    _run(cmd_today(update, _context(conn, monday)))
    assert len(update.replies) == 1
    assert "Lunes" in update.replies[0]
    assert "Martes" not in update.replies[0]


# --- /shopping -----------------------------------------------------------


def test_shopping_with_no_plan_suggests_regenerate(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_shopping(update, _context(conn, date(2026, 9, 21))))
    assert update.replies == [NO_PLAN_MESSAGE]


def test_shopping_renders_the_aggregated_list(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    update = _update()
    _run(cmd_shopping(update, _context(conn, monday)))
    assert len(update.replies) == 1
    assert "Despensa:" in update.replies[0]
    assert update.replies[0].count("food-") > 0


def test_shopping_splits_into_several_messages_when_long(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    # Every dish gets its own food with a deliberately long name, so the
    # aggregated list (one line per food, all distinct) overflows the
    # single-message limit and must be split at a category boundary.
    counts = {MealType.BREAKFAST: 6, MealType.SNACK: 12, MealType.LUNCH: 6, MealType.DINNER: 6}
    for meal_type, count in counts.items():
        for i in range(count):
            food = repo.create_food(
                conn,
                name=f"Ingrediente{'X' * 350}-{meal_type.value}-{i:03d}",
                unit=Unit.G,
                category=Category.PANTRY,
                kcal_ref=100.0,
            )
            repo.create_dish(
                conn,
                name=f"{meal_type.value}-{i}",
                meal_type=meal_type,
                ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
                kcal_override=400,
            )

    catalogue = repo.list_dishes(conn, archived=False)
    plan = plan_week(catalogue, [], planner_settings(conn), monday, random.Random(3))
    repo.save_plan(conn, plan)

    update = _update()
    _run(cmd_shopping(update, _context(conn, monday)))
    assert len(update.replies) > 1


def test_reply_only_goes_to_the_calling_chat_not_the_group(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    group_chat_id = -1001
    private_chat_id = 555
    assert group_chat_id != private_chat_id

    update = _update(chat_id=private_chat_id, chat_type="private")
    _run(cmd_plan(update, _context(conn, monday)))
    assert len(update.replies) == 1
    # The handler has no notion of a group chat id at all: it only ever
    # calls update.reply_text, which this fake records on the one update
    # object it was given.


# --- parse_swap_args -------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["lunes", "cena"], (0, Slot.DINNER)),
        (["1", "cena"], (0, Slot.DINNER)),
        (["VIERNES", "Snack2"], (4, Slot.SNACK2)),
        (["lunes", "cena", "siguiente"], (0, Slot.DINNER)),
    ],
)
def test_swap_argument_parsing(args: list[str], expected: tuple[int, Slot]) -> None:
    day, slot, _is_next = parse_swap_args(args)
    assert (day, slot) == expected


def test_swap_accepts_an_accented_day() -> None:
    assert parse_swap_args(["miércoles", "comida"]) == (2, Slot.LUNCH, False)


def test_swap_resolves_the_week() -> None:
    assert parse_swap_args(["lunes", "cena"])[2] is False
    assert parse_swap_args(["lunes", "cena", "siguiente"])[2] is True


@pytest.mark.parametrize(
    "args", [[], ["lunes"], ["sabado", "cena"], ["1", "merienda"], ["9", "cena"]]
)
def test_swap_rejects_bad_arguments(args: list[str]) -> None:
    with pytest.raises(ArgumentError):
        parse_swap_args(args)


# --- /regenerate ------------------------------------------------------


def _entries_by_slot(plan: Plan) -> dict[tuple[int, Slot], int]:
    return {(e.day, e.slot): e.dish_id for e in plan.entries}


def _seed_dish(conn: sqlite3.Connection, meal_type: MealType, index: int) -> None:
    food = repo.create_food(
        conn,
        name=f"{meal_type.value}-food-{index}",
        unit=Unit.G,
        category=Category.PANTRY,
        kcal_ref=100.0,
    )
    repo.create_dish(
        conn,
        name=f"{meal_type.value}-{index}",
        meal_type=meal_type,
        ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
        kcal_override=400,
    )


def test_regenerate_replaces_the_week_and_shows_relaxation_notice(
    conn: sqlite3.Connection,
) -> None:
    monday = date(2026, 9, 21)
    # Only three breakfast dishes for five weekday slots forces a repeat; a
    # five-day cooldown makes the unrelaxed attempt provably infeasible
    # (max gap across a five-day week is four), so this exercises the
    # relaxation ladder for real rather than asserting on a contrivance.
    for i in range(3):
        _seed_dish(conn, MealType.BREAKFAST, i)
    for meal_type, count in {MealType.SNACK: 10, MealType.LUNCH: 6, MealType.DINNER: 6}.items():
        for i in range(count):
            _seed_dish(conn, meal_type, i)
    repo.set_setting(conn, "cooldown_days_breakfast", "5")

    update = _update()
    _run(cmd_regenerate(update, _context(conn, monday, seed=7)))

    assert len(update.replies) == 1
    text = update.replies[0]
    assert "Plan de esta semana" in text

    stored = repo.get_plan(conn, monday)
    assert stored is not None
    assert stored.relaxation >= 1
    assert render_relaxation_notice(stored.relaxation) in text


def test_regenerate_reports_diagnosis_and_saves_nothing_on_failure(
    conn: sqlite3.Connection,
) -> None:
    monday = date(2026, 9, 21)
    # No lunch dishes at all: the planner can never fill that slot at any
    # relaxation step, so plan_week is guaranteed to raise PlannerFailure.
    for meal_type, count in {MealType.BREAKFAST: 5, MealType.SNACK: 10, MealType.DINNER: 5}.items():
        for i in range(count):
            _seed_dish(conn, meal_type, i)

    update = _update()
    _run(cmd_regenerate(update, _context(conn, monday)))

    assert len(update.replies) == 1
    assert "Comida" in update.replies[0]
    assert repo.get_plan(conn, monday) is None


def test_regenerate_rejects_unparseable_argument(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_regenerate(update, _context(conn, date(2026, 9, 21), ["martes"])))
    assert update.replies == ["No entendí ese argumento."]
    assert repo.get_plan(conn, date(2026, 9, 21)) is None


def test_regenerate_siguiente_draws_next_week_leaving_current_untouched(
    conn: sqlite3.Connection,
) -> None:
    current_start = date(2026, 9, 21)
    next_start = date(2026, 9, 28)
    _seed_full_catalogue(conn)
    catalogue = repo.list_dishes(conn, archived=False)
    settings = planner_settings(conn)
    current_plan = plan_week(catalogue, [], settings, current_start, random.Random(9))
    repo.save_plan(conn, current_plan)

    update = _update()
    _run(cmd_regenerate(update, _context(conn, current_start, ["siguiente"], seed=11)))

    stored_current = repo.get_plan(conn, current_start)
    assert stored_current is not None
    assert _entries_by_slot(stored_current) == _entries_by_slot(current_plan)
    next_plan = repo.get_plan(conn, next_start)
    assert next_plan is not None
    assert "Plan de la semana que viene" in update.replies[0]


# --- /swap ---------------------------------------------------------------


def test_swap_redraws_one_slot_and_keeps_the_rest(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    before = repo.get_plan(conn, monday)
    assert before is not None
    other_before = tuple(e for e in before.entries if not (e.day == 0 and e.slot == Slot.DINNER))

    update = _update()
    _run(cmd_swap(update, _context(conn, monday, ["lunes", "cena"], seed=5)))

    after = repo.get_plan(conn, monday)
    assert after is not None
    other_after = tuple(e for e in after.entries if not (e.day == 0 and e.slot == Slot.DINNER))
    assert other_before == other_after
    assert len(update.replies) == 1
    assert "Lunes" in update.replies[0]


def test_swap_with_no_plan_suggests_regenerate(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_swap(update, _context(conn, date(2026, 9, 21), ["lunes", "cena"])))
    assert update.replies == [NO_PLAN_MESSAGE]


def test_swap_handler_rejects_bad_arguments_and_changes_nothing(
    conn: sqlite3.Connection,
) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    before = repo.get_plan(conn, monday)

    update = _update()
    _run(cmd_swap(update, _context(conn, monday, ["martes"])))

    assert update.replies == [SWAP_USAGE_MESSAGE]
    assert repo.get_plan(conn, monday) == before


def test_swap_unsatisfiable_leaves_existing_assignment(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    before = repo.get_plan(conn, monday)
    assert before is not None
    for dish in repo.list_dishes(conn, archived=False):
        if dish.meal_type == MealType.DINNER:
            repo.deactivate_dish(conn, dish.id, monday)

    update = _update()
    _run(cmd_swap(update, _context(conn, monday, ["lunes", "cena"])))

    assert update.replies == [render_swap_unsatisfiable()]
    assert repo.get_plan(conn, monday) == before


def test_swap_does_not_post_to_the_group_from_a_private_chat(conn: sqlite3.Connection) -> None:
    monday = date(2026, 9, 21)
    _seed_plan(conn, monday)
    group_chat_id = -1001
    private_chat_id = 777
    assert group_chat_id != private_chat_id

    update = _update(chat_id=private_chat_id, chat_type="private")
    _run(cmd_swap(update, _context(conn, monday, ["lunes", "cena"], seed=13)))
    assert len(update.replies) == 1


# --- parse_callback --------------------------------------------------------


def test_parse_callback_dishes_page() -> None:
    assert parse_callback("dishes:2:0") == DishesPageCallback(page=2, archived=False)
    assert parse_callback("dishes:3:1") == DishesPageCallback(page=3, archived=True)


def test_parse_callback_dish() -> None:
    assert parse_callback("dish:42") == DishCallback(dish_id=42)


def test_parse_callback_restore() -> None:
    assert parse_callback("restore:dish:7") == RestoreCallback(kind="dish", item_id=7)
    assert parse_callback("restore:food:9") == RestoreCallback(kind="food", item_id=9)


@pytest.mark.parametrize(
    "data",
    [
        "",
        "dishes:x:0",
        "dishes:1:2",
        "dish:abc",
        "restore:plate:1",
        "restore:dish:x",
        "unknown:1",
        "dishes:1",
        "dish:1:2",
    ],
)
def test_parse_callback_rejects_malformed_data(data: str) -> None:
    assert parse_callback(data) is None


# --- /dishes ---------------------------------------------------------------


def _seed_dishes(
    conn: sqlite3.Connection, count: int, meal_type: MealType = MealType.LUNCH
) -> None:
    for i in range(count):
        food = repo.create_food(
            conn,
            name=f"food-{meal_type.value}-{i}",
            unit=Unit.G,
            category=Category.PANTRY,
            kcal_ref=100.0,
        )
        repo.create_dish(
            conn,
            name=f"Plato{i:02d}",
            meal_type=meal_type,
            ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
        )


def test_dishes_paginates_at_twenty_with_working_next_and_previous_buttons(
    conn: sqlite3.Connection,
) -> None:
    _seed_dishes(conn, 25)
    update = _update()
    _run(cmd_dishes(update, _context(conn, date(2026, 9, 21))))

    assert "Página 1 de 2" in update.replies[0]
    assert update.replies[0].count("Plato") == 20
    keyboard = update.markups[0]
    assert keyboard is not None
    next_button = next(b for row in keyboard for b in row if b[0] == PAGINATION_NEXT_BUTTON)

    query = FakeCallbackQuery(data=next_button[1])
    callback_update = _update(callback_query=query)
    _run(on_catalog_callback(callback_update, _context(conn, date(2026, 9, 21))))

    assert query.answered
    assert "Página 2 de 2" in query.edits[0]
    assert query.edits[0].count("Plato") == 5
    assert query.edits[0] != update.replies[0]

    # and back to page one via the "previous" button on the edited keyboard
    prev_keyboard = query.edit_markups[0]
    assert prev_keyboard is not None
    prev_button = next(b for row in prev_keyboard for b in row if b[0] != PAGINATION_NEXT_BUTTON)
    query2 = FakeCallbackQuery(data=prev_button[1])
    callback_update2 = _update(callback_query=query2)
    _run(on_catalog_callback(callback_update2, _context(conn, date(2026, 9, 21))))
    assert "Página 1 de 2" in query2.edits[0]


def test_dishes_archivados_lists_inactive_with_pagination(conn: sqlite3.Connection) -> None:
    food = repo.create_food(conn, name="X", unit=Unit.G, category=Category.OTHER, kcal_ref=1.0)
    dish = repo.create_dish(
        conn,
        name="Viejo",
        meal_type=MealType.DINNER,
        ingredients=[DishIngredient(food_id=food.id, quantity=1.0)],
    )
    repo.deactivate_dish(conn, dish.id, date(2026, 9, 21))

    update = _update()
    _run(cmd_dishes(update, _context(conn, date(2026, 9, 21), ["archivados"])))
    assert "Viejo" in update.replies[0]
    assert "Página 1 de 1" in update.replies[0]

    # the active list, meanwhile, is empty
    active_update = _update()
    _run(cmd_dishes(active_update, _context(conn, date(2026, 9, 21))))
    assert "Viejo" not in active_update.replies[0]


# --- /dish -------------------------------------------------------------


def test_dish_exact_match_returns_the_full_card(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0
    )
    repo.create_dish(
        conn,
        name="Arroz con pollo",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food.id, quantity=150.0)],
        steps="Cocinar el arroz.",
    )
    update = _update()
    _run(cmd_dish(update, _context(conn, date(2026, 9, 21), ["Arroz", "con", "pollo"])))
    assert len(update.replies) == 1
    assert "Arroz con pollo" in update.replies[0]
    assert "Cocinar el arroz." in update.replies[0]


def test_dish_partial_match_offers_buttons_and_tapping_one_returns_the_card(
    conn: sqlite3.Connection,
) -> None:
    food = repo.create_food(
        conn, name="Pollo", unit=Unit.G, category=Category.MEAT_FISH, kcal_ref=200.0
    )
    for i in range(3):
        repo.create_dish(
            conn,
            name=f"Pollo receta {i}",
            meal_type=MealType.DINNER,
            ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
        )

    update = _update()
    _run(cmd_dish(update, _context(conn, date(2026, 9, 21), ["Pollo"])))
    assert update.replies == [DISH_FUZZY_PROMPT]
    keyboard = update.markups[0]
    assert keyboard is not None
    label, callback_data = keyboard[0][0]

    query = FakeCallbackQuery(data=callback_data)
    callback_update = _update(callback_query=query)
    _run(on_catalog_callback(callback_update, _context(conn, date(2026, 9, 21))))
    assert query.answered
    assert label in query.edits[0]


def test_dish_partial_match_caps_at_five_buttons(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Base", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )
    for i in range(7):
        repo.create_dish(
            conn,
            name=f"Sopa {i}",
            meal_type=MealType.LUNCH,
            ingredients=[DishIngredient(food_id=food.id, quantity=100.0)],
        )
    update = _update()
    _run(cmd_dish(update, _context(conn, date(2026, 9, 21), ["Sopa"])))
    keyboard = update.markups[0]
    assert keyboard is not None
    assert len(keyboard[0]) == 5


def test_dish_no_match_says_so(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_dish(update, _context(conn, date(2026, 9, 21), ["Inexistente"])))
    assert update.replies == [DISH_NOT_FOUND_MESSAGE]


def test_dish_shows_whether_calories_are_computed_or_overridden(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Base2", unit=Unit.G, category=Category.PANTRY, kcal_ref=100.0
    )
    repo.create_dish(
        conn,
        name="Computado",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food.id, quantity=200.0)],
    )
    repo.create_dish(
        conn,
        name="Fijado",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food.id, quantity=200.0)],
        kcal_override=999,
    )

    update = _update()
    _run(cmd_dish(update, _context(conn, date(2026, 9, 21), ["Computado"])))
    assert "calculadas" in update.replies[0]

    update2 = _update()
    _run(cmd_dish(update2, _context(conn, date(2026, 9, 21), ["Fijado"])))
    assert "fijadas manualmente" in update2.replies[0]


# --- /foods ------------------------------------------------------------


def test_foods_groups_by_category_order_with_unit_and_kcal(conn: sqlite3.Connection) -> None:
    repo.create_food(conn, name="Manzana", unit=Unit.UNIT, category=Category.PRODUCE, kcal_ref=95.0)
    repo.create_food(conn, name="Leche", unit=Unit.ML, category=Category.DAIRY_EGGS, kcal_ref=42.0)

    update = _update()
    _run(cmd_foods(update, _context(conn, date(2026, 9, 21))))
    text = update.replies[0]
    assert text.index("Frutas y verduras") < text.index("Lácteos y huevos")
    assert "Manzana: ud, 95 kcal de referencia" in text
    assert "Leche: ml, 42 kcal de referencia" in text


def test_foods_archivados_lists_inactive_foods(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Descontinuado", unit=Unit.G, category=Category.OTHER, kcal_ref=1.0
    )
    repo.deactivate_food(conn, food.id)

    update = _update()
    _run(cmd_foods(update, _context(conn, date(2026, 9, 21), ["archivados"])))
    assert "Descontinuado" in update.replies[0]

    active_update = _update()
    _run(cmd_foods(active_update, _context(conn, date(2026, 9, 21))))
    assert "Descontinuado" not in active_update.replies[0]


# --- /restore ------------------------------------------------------------


def test_restore_reactivates_an_archived_dish_by_exact_name(conn: sqlite3.Connection) -> None:
    food = repo.create_food(conn, name="Y", unit=Unit.G, category=Category.OTHER, kcal_ref=1.0)
    dish = repo.create_dish(
        conn,
        name="Guiso Antiguo",
        meal_type=MealType.DINNER,
        ingredients=[DishIngredient(food_id=food.id, quantity=1.0)],
    )
    repo.deactivate_dish(conn, dish.id, date(2026, 9, 21))

    update = _update()
    _run(cmd_restore(update, _context(conn, date(2026, 9, 21), ["Guiso", "Antiguo"])))

    restored = repo.get_dish(conn, dish.id)
    assert restored.active
    assert update.replies == [render_restored_dish(restored)]


def test_restore_reactivates_an_archived_food_by_exact_name(conn: sqlite3.Connection) -> None:
    food = repo.create_food(
        conn, name="Miel", unit=Unit.G, category=Category.PANTRY, kcal_ref=300.0
    )
    repo.deactivate_food(conn, food.id)

    update = _update()
    _run(cmd_restore(update, _context(conn, date(2026, 9, 21), ["Miel"])))

    assert any(f.name == "Miel" for f in repo.list_foods(conn, archived=False))
    assert update.replies == [render_restored_food(repo.get_food_by_exact_name(conn, "Miel"))]  # type: ignore[arg-type]


def test_restore_offers_buttons_when_the_name_matches_more_than_one(
    conn: sqlite3.Connection,
) -> None:
    for i in range(2):
        food = repo.create_food(
            conn, name=f"Sopa Fria food {i}", unit=Unit.G, category=Category.OTHER, kcal_ref=1.0
        )
        dish = repo.create_dish(
            conn,
            name=f"Sopa Fria {i}",
            meal_type=MealType.DINNER,
            ingredients=[DishIngredient(food_id=food.id, quantity=1.0)],
        )
        repo.deactivate_dish(conn, dish.id, date(2026, 9, 21))

    update = _update()
    _run(cmd_restore(update, _context(conn, date(2026, 9, 21), ["Sopa", "Fria"])))
    assert update.replies == [RESTORE_AMBIGUOUS_PROMPT]
    keyboard = update.markups[0]
    assert keyboard is not None
    assert len(keyboard[0]) == 2

    _label, callback_data = keyboard[0][0]
    query = FakeCallbackQuery(data=callback_data)
    callback_update = _update(callback_query=query)
    _run(on_catalog_callback(callback_update, _context(conn, date(2026, 9, 21))))
    assert query.answered
    assert len(query.edits) == 1


def test_restore_says_so_when_nothing_matches(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(cmd_restore(update, _context(conn, date(2026, 9, 21), ["Nada"])))
    assert update.replies == [RESTORE_NOT_FOUND_MESSAGE]


def test_restore_refuses_the_group_chat(conn: sqlite3.Connection) -> None:
    update = _update(chat_id=-1001, chat_type="group")
    _run(cmd_restore(update, _context(conn, date(2026, 9, 21), ["Nada"])))
    assert update.replies == ["Ese comando solo funciona en un chat privado conmigo."]


# --- callback robustness ---------------------------------------------------


def test_callback_with_malformed_data_does_not_raise(conn: sqlite3.Connection) -> None:
    query = FakeCallbackQuery(data="garbage:xx")
    update = _update(callback_query=query)
    _run(on_catalog_callback(update, _context(conn, date(2026, 9, 21))))
    assert query.answered
    assert query.edits == []


def test_callback_with_no_query_is_a_noop(conn: sqlite3.Connection) -> None:
    update = _update()
    _run(on_catalog_callback(update, _context(conn, date(2026, 9, 21))))
    assert update.replies == []


def test_foods_paginates_at_twenty_with_working_next_button(conn: sqlite3.Connection) -> None:
    for index in range(25):
        repo.create_food(
            conn,
            name=f"Alimento {index:02d}",
            unit=Unit.G,
            category=Category.PANTRY,
            kcal_ref=100.0,
        )
    update = _update()
    _run(cmd_foods(update, _context(conn, date(2026, 9, 21))))

    assert "Página 1 de 2" in update.replies[0]
    assert update.replies[0].count("Alimento") == 20
    keyboard = update.markups[0]
    assert keyboard is not None
    next_button = next(b for row in keyboard for b in row if b[0] == PAGINATION_NEXT_BUTTON)

    query = FakeCallbackQuery(data=next_button[1])
    _run(on_catalog_callback(_update(callback_query=query), _context(conn, date(2026, 9, 21))))

    assert query.answered
    assert "Página 2 de 2" in query.edits[0]
    assert query.edits[0].count("Alimento") == 5
    assert query.edits[0] != update.replies[0]


def test_foods_archivados_paginates_too(conn: sqlite3.Connection) -> None:
    for index in range(22):
        food = repo.create_food(
            conn,
            name=f"Retirado {index:02d}",
            unit=Unit.G,
            category=Category.PANTRY,
            kcal_ref=100.0,
        )
        repo.deactivate_food(conn, food.id)

    update = _update()
    _run(cmd_foods(update, _context(conn, date(2026, 9, 21), ["archivados"])))

    assert "Página 1 de 2" in update.replies[0]
    keyboard = update.markups[0]
    assert keyboard is not None
    next_button = next(b for row in keyboard for b in row if b[0] == PAGINATION_NEXT_BUTTON)
    assert next_button[1] == "foods:2:1"


# --- entry point: build_application, access gating, commands, logging -----

TEST_CONFIG = Config(
    token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
    allowed_user_ids=frozenset({1}),
    group_chat_id=-1001,
    db_path=Path("/tmp/unused-meal_planning_bot-test.db"),
    timezone="UTC",
    log_level="INFO",
)


def _build_app(conn: sqlite3.Connection) -> Any:
    bot = ExtBot(token=TEST_CONFIG.token)
    return build_application(TEST_CONFIG, conn, bot=bot)


def test_every_handler_is_gated_except_myid(conn: sqlite3.Connection) -> None:
    app = _build_app(conn)
    seen_myid = False
    checked = 0
    for group in app.handlers.values():
        for handler in group:
            commands = getattr(handler, "commands", frozenset())
            if "myid" in commands:
                seen_myid = True
                # /myid must NOT be access-gated -- it must answer any user.
                assert getattr(handler.callback, "__access_gated__", False) is False
                continue
            checked += 1
            assert getattr(handler.callback, "__access_gated__", False) is True

    assert seen_myid
    # Sanity: this walk actually inspected more than a token handful of
    # handlers, so the assertion above is not vacuously true.
    assert checked >= 20


def test_command_list_matches_formatting_commands(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[Any] = []

    async def fake_set_my_commands(self: Any, commands: Any, **kwargs: Any) -> bool:
        recorded.append(list(commands))
        return True

    monkeypatch.setattr(ExtBot, "set_my_commands", fake_set_my_commands)

    app = _build_app(conn)
    assert app.post_init is not None
    asyncio.run(app.post_init(app))

    assert len(recorded) == 1
    sent = recorded[0]
    assert [(c.command, c.description) for c in sent] == [(c.name, c.description) for c in COMMANDS]


def test_logging_is_configured_at_the_configured_level(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: seen.append(kwargs))

    _configure_logging(replace(TEST_CONFIG, log_level="DEBUG"))

    assert seen[-1]["level"] == "DEBUG"


def test_token_never_appears_in_a_log_record(caplog: pytest.LogCaptureFixture) -> None:
    secret_config = replace(TEST_CONFIG, token="super-secret-token-xyz")
    logger = logging.getLogger("meal_planning_bot.test_token_leak")

    with caplog.at_level(logging.DEBUG):
        logger.info("built config %s", secret_config)

    assert "super-secret-token-xyz" not in caplog.text
