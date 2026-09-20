import sqlite3
from datetime import date
from pathlib import Path

import pytest

from meal_planning_bot import repo
from meal_planning_bot.models import (
    SLOT_MEAL_TYPE,
    SLOT_ORDER,
    Category,
    DishIngredient,
    MealType,
    Plan,
    PlanEntry,
    Slot,
    Unit,
)
from meal_planning_bot.weeks import current_week_start, next_week_start

TODAY = date(2026, 9, 16)


def _food(
    conn: sqlite3.Connection,
    name: str = "Arroz",
    unit: Unit = Unit.G,
    category: Category = Category.PANTRY,
    kcal_ref: float = 360.0,
) -> int:
    food = repo.create_food(conn, name=name, unit=unit, category=category, kcal_ref=kcal_ref)
    return food.id


SQL_LAYER = {"repo.py", "db.py", "migrations.py"}
SQL_EXECUTION = ("execute(", "executemany(", "executescript(", "sqlite3.connect", "import connect")


def test_only_the_sql_layer_executes_sql() -> None:
    """Importing sqlite3.Connection for a type annotation is fine; running SQL is not.

    An earlier version of this test matched the literal string "import sqlite3", which any
    module could evade with `from sqlite3 import connect` -- and one did. It looked for a
    spelling instead of the behaviour it was meant to forbid.
    """
    offenders: list[str] = []
    for path in Path("meal_planning_bot").rglob("*.py"):
        if path.name in SQL_LAYER:
            continue
        source = path.read_text()
        for line in source.splitlines():
            code = line.split("#", 1)[0]
            if any(marker in code for marker in SQL_EXECUTION):
                offenders.append(f"{path}: {line.strip()}")
    assert offenders == []


# --- foods -----------------------------------------------------------------


def test_create_food_stores_kcal_ref_and_preserves_capitalisation(
    conn: sqlite3.Connection,
) -> None:
    food = repo.create_food(
        conn, name="Pollo", unit=Unit.G, category=Category.MEAT_FISH, kcal_ref=165.0
    )
    assert food.name == "Pollo"
    assert food.kcal_ref == 165.0
    assert food.active is True


def test_create_food_rejects_case_variant_duplicate(conn: sqlite3.Connection) -> None:
    repo.create_food(conn, name="Pollo", unit=Unit.G, category=Category.MEAT_FISH, kcal_ref=165.0)
    with pytest.raises(ValueError):
        repo.create_food(
            conn, name="pollo", unit=Unit.G, category=Category.MEAT_FISH, kcal_ref=165.0
        )


def test_update_food_unit_change_requires_new_kcal_ref(conn: sqlite3.Connection) -> None:
    food_id = _food(conn, unit=Unit.G, kcal_ref=360.0)
    with pytest.raises(ValueError):
        repo.update_food(conn, food_id, unit=Unit.ML)


def test_update_food_unit_change_leaves_quantities_untouched(conn: sqlite3.Connection) -> None:
    food_id = _food(conn, unit=Unit.G, kcal_ref=360.0)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=200.0)],
    )
    repo.update_food(conn, food_id, unit=Unit.ML, kcal_ref=100.0)
    reloaded = repo.get_dish(conn, dish.id)
    assert reloaded.ingredients[0].quantity == 200.0


def test_deactivate_food_refused_while_referenced(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=200.0)],
    )
    with pytest.raises(repo.FoodInUse) as exc_info:
        repo.deactivate_food(conn, food_id)
    assert "Arroz blanco" in exc_info.value.dish_names


def test_deactivate_and_reactivate_food(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    repo.deactivate_food(conn, food_id)
    assert repo.list_foods(conn) == []
    assert [f.id for f in repo.list_foods(conn, archived=True)] == [food_id]
    reactivated = repo.reactivate_food(conn, food_id)
    assert reactivated.active is True
    assert [f.id for f in repo.list_foods(conn)] == [food_id]


def test_list_foods_active_only(conn: sqlite3.Connection) -> None:
    active_id = _food(conn, name="Arroz")
    archived_id = _food(conn, name="Pasta")
    repo.deactivate_food(conn, archived_id)
    assert [f.id for f in repo.list_foods(conn)] == [active_id]


def test_find_foods_by_name(conn: sqlite3.Connection) -> None:
    _food(conn, name="Arroz integral")
    _food(conn, name="Pasta")
    matches = repo.find_foods_by_name(conn, "arroz")
    assert [f.name for f in matches] == ["Arroz integral"]


def test_get_food_by_exact_name(conn: sqlite3.Connection) -> None:
    _food(conn, name="Arroz")
    assert repo.get_food_by_exact_name(conn, "ARROZ") is not None
    assert repo.get_food_by_exact_name(conn, "nada") is None


# --- dishes ------------------------------------------------------------


def test_create_dish_rejects_empty_ingredients(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        repo.create_dish(conn, name="X", meal_type=MealType.LUNCH, ingredients=[])


def test_create_dish_rejects_duplicated_food(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    with pytest.raises(ValueError):
        repo.create_dish(
            conn,
            name="X",
            meal_type=MealType.LUNCH,
            ingredients=[
                DishIngredient(food_id=food_id, quantity=100.0),
                DishIngredient(food_id=food_id, quantity=50.0),
            ],
        )


def test_create_dish_rejects_case_variant_duplicate_name(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    with pytest.raises(ValueError):
        repo.create_dish(
            conn,
            name="arroz blanco",
            meal_type=MealType.LUNCH,
            ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
        )


def test_failed_dish_creation_leaves_nothing(conn: sqlite3.Connection) -> None:
    before = conn.execute("SELECT count(*) FROM foods").fetchone()[0]
    with pytest.raises(ValueError):
        repo.create_dish(
            conn, name="X", meal_type=MealType.LUNCH, kcal_override=500, ingredients=[]
        )
    assert conn.execute("SELECT count(*) FROM foods").fetchone()[0] == before
    assert conn.execute("SELECT count(*) FROM dishes").fetchone()[0] == 0


def test_dish_kcal_is_resolved_from_ingredients(conn: sqlite3.Connection) -> None:
    food_id = _food(conn, unit=Unit.G, kcal_ref=360.0)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=200.0)],
    )
    assert dish.kcal == 720


def test_dish_kcal_override_wins(conn: sqlite3.Connection) -> None:
    food_id = _food(conn, unit=Unit.G, kcal_ref=360.0)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=200.0)],
        kcal_override=999,
    )
    assert dish.kcal == 999


def test_deactivate_dish_keeps_ingredients_and_plan_entries(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    week_start = current_week_start(date.today())
    repo.save_plan(
        conn,
        Plan(week_start=week_start, entries=(PlanEntry(day=0, slot=Slot.LUNCH, dish_id=dish.id),)),
    )

    affected = repo.deactivate_dish(conn, dish.id, TODAY)

    assert (week_start, 0, Slot.LUNCH) in affected
    row = conn.execute("SELECT active FROM dishes WHERE id = ?", (dish.id,)).fetchone()
    assert row["active"] == 0
    ingredient_rows = conn.execute(
        "SELECT * FROM dish_ingredients WHERE dish_id = ?", (dish.id,)
    ).fetchall()
    assert len(ingredient_rows) == 1
    entry_rows = conn.execute("SELECT * FROM plan_entries WHERE dish_id = ?", (dish.id,)).fetchall()
    assert len(entry_rows) == 1


def test_deactivate_dish_reports_current_and_next_week(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    today = date(2026, 9, 16)
    current = current_week_start(today)
    nxt = next_week_start(today)
    repo.save_plan(
        conn,
        Plan(week_start=current, entries=(PlanEntry(day=0, slot=Slot.LUNCH, dish_id=dish.id),)),
    )
    repo.save_plan(
        conn, Plan(week_start=nxt, entries=(PlanEntry(day=1, slot=Slot.LUNCH, dish_id=dish.id),))
    )

    affected = repo.deactivate_dish(conn, dish.id, today)

    assert set(affected) == {(current, 0, Slot.LUNCH), (nxt, 1, Slot.LUNCH)}


def test_reactivate_dish_and_list_archived(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    repo.deactivate_dish(conn, dish.id, TODAY)
    assert repo.list_dishes(conn) == []
    assert [d.id for d in repo.list_dishes(conn, archived=True)] == [dish.id]
    reactivated = repo.reactivate_dish(conn, dish.id)
    assert reactivated.active is True
    assert [d.id for d in repo.list_dishes(conn)] == [dish.id]


def test_list_dishes_active_only(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    active = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    archived = repo.create_dish(
        conn,
        name="Pasta blanca",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    repo.deactivate_dish(conn, archived.id, TODAY)
    assert [d.id for d in repo.list_dishes(conn)] == [active.id]


def test_count_dishes_by_meal_type(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    repo.create_dish(
        conn,
        name="Tostada",
        meal_type=MealType.BREAKFAST,
        ingredients=[DishIngredient(food_id=food_id, quantity=50.0)],
    )
    counts = repo.count_dishes_by_meal_type(conn)
    assert counts[MealType.LUNCH] == 1
    assert counts[MealType.BREAKFAST] == 1
    assert counts[MealType.DINNER] == 0


def test_find_dishes_by_name(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    matches = repo.find_dishes_by_name(conn, "arroz")
    assert [d.name for d in matches] == ["Arroz blanco"]


def test_get_dish_unknown_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        repo.get_dish(conn, 999)


def test_update_dish_meal_type_change_does_not_touch_stored_plans(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    week_start = current_week_start(date.today())
    repo.save_plan(
        conn,
        Plan(week_start=week_start, entries=(PlanEntry(day=0, slot=Slot.LUNCH, dish_id=dish.id),)),
    )

    repo.update_dish(conn, dish.id, meal_type=MealType.DINNER)

    plan = repo.get_plan(conn, week_start)
    assert plan is not None
    assert plan.entries[0].dish_id == dish.id


# --- plans and history ------------------------------------------------


def _full_plan(week_start_date: "date", dish_ids: list[int]) -> "Plan":
    entries = tuple(
        PlanEntry(day=day, slot=slot, dish_id=dish_ids[day % len(dish_ids)])
        for day in range(5)
        for slot in SLOT_ORDER
    )
    return Plan(week_start=week_start_date, entries=entries)


def test_get_plan_returns_none_when_absent(conn: sqlite3.Connection) -> None:
    assert repo.get_plan(conn, date(2026, 9, 14)) is None


def test_get_plan_returns_all_entries(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    week_start = date(2026, 9, 14)
    repo.save_plan(conn, _full_plan(week_start, [dish.id]))
    plan = repo.get_plan(conn, week_start)
    assert plan is not None
    assert len(plan.entries) == 25


def test_save_plan_is_idempotent_per_week(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish_a = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    dish_b = repo.create_dish(
        conn,
        name="Pasta blanca",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    week_start = date(2026, 9, 14)
    repo.save_plan(conn, _full_plan(week_start, [dish_a.id]))
    repo.save_plan(conn, _full_plan(week_start, [dish_b.id]))

    plan_count = conn.execute("SELECT count(*) FROM plans").fetchone()[0]
    assert plan_count == 1

    plan = repo.get_plan(conn, week_start)
    assert plan is not None
    assert all(e.dish_id == dish_b.id for e in plan.entries)


def test_scheduled_history_maps_day_to_real_date(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    week_start = date(2026, 9, 14)
    repo.save_plan(
        conn,
        Plan(week_start=week_start, entries=(PlanEntry(day=2, slot=Slot.LUNCH, dish_id=dish.id),)),
    )

    history = repo.scheduled_history(conn, around=date(2026, 9, 18), days=60)
    served_dates = [r.served_on for r in history if r.dish_id == dish.id]
    assert date(2026, 9, 16) in served_dates


def test_scheduled_history_includes_future_stored_plan(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dish = repo.create_dish(
        conn,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
    )
    this_week = date(2026, 9, 14)
    next_week = date(2026, 9, 21)
    repo.save_plan(
        conn,
        Plan(week_start=next_week, entries=(PlanEntry(day=0, slot=Slot.LUNCH, dish_id=dish.id),)),
    )

    history = repo.scheduled_history(conn, around=this_week, days=60)
    assert any(r.dish_id == dish.id and r.served_on == next_week for r in history)


def test_saved_plan_round_trips_with_slots_in_order(conn: sqlite3.Connection) -> None:
    food_id = _food(conn)
    dishes = {
        meal_type: repo.create_dish(
            conn,
            name=f"plato {meal_type.value}",
            meal_type=meal_type,
            ingredients=[DishIngredient(food_id=food_id, quantity=100.0)],
        ).id
        for meal_type in MealType
    }
    entries = tuple(
        PlanEntry(day=day, slot=slot, dish_id=dishes[SLOT_MEAL_TYPE[slot]])
        for day in range(5)
        for slot in SLOT_ORDER
    )
    saved = Plan(week_start=date(2026, 9, 14), entries=entries)
    repo.save_plan(conn, saved)

    read_back = repo.get_plan(conn, date(2026, 9, 14))

    assert read_back is not None
    assert read_back.entries == saved.entries
