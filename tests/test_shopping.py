from datetime import date

import pytest

from meal_planning_bot.models import (
    Category,
    Dish,
    DishIngredient,
    Food,
    MealType,
    Plan,
    PlanEntry,
    Slot,
    Unit,
)
from meal_planning_bot.shopping import _render_quantity, aggregate

WEEK_START = date(2026, 9, 21)

FOOD_RICE = Food(id=10, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
FOOD_CHICKEN = Food(id=11, name="Pollo", unit=Unit.G, category=Category.MEAT_FISH, kcal_ref=165.0)
FOOD_MILK = Food(id=12, name="Leche", unit=Unit.ML, category=Category.DAIRY_EGGS, kcal_ref=42.0)
FOOD_EGG = Food(id=13, name="Huevo", unit=Unit.UNIT, category=Category.DAIRY_EGGS, kcal_ref=70.0)
FOOD_APPLE = Food(id=14, name="manzana", unit=Unit.UNIT, category=Category.PRODUCE, kcal_ref=52.0)


def dish_with(id: int, foods: dict[int, float], meal_type: MealType = MealType.LUNCH) -> Dish:
    return Dish(
        id=id,
        name=f"dish{id}",
        meal_type=meal_type,
        kcal=0,
        ingredients=tuple(DishIngredient(food_id=fid, quantity=q) for fid, q in foods.items()),
    )


def plan_with(entries: list[tuple[int, Slot, int]]) -> Plan:
    return Plan(
        week_start=WEEK_START,
        entries=tuple(PlanEntry(day=d, slot=s, dish_id=did) for d, s, did in entries),
    )


def test_counts_a_dish_drawn_twice() -> None:
    plan = plan_with([(0, Slot.LUNCH, 1), (1, Slot.LUNCH, 1)])
    groups = aggregate(plan, {1: dish_with(1, {10: 150.0})}, {10: FOOD_RICE})
    assert groups[0].lines[0].quantity == "300"


def test_sums_a_food_used_by_three_dishes() -> None:
    plan = plan_with([(0, Slot.LUNCH, 1), (1, Slot.DINNER, 2), (2, Slot.BREAKFAST, 3)])
    dishes = {
        1: dish_with(1, {10: 100.0}),
        2: dish_with(2, {10: 50.0}),
        3: dish_with(3, {10: 25.0}),
    }
    groups = aggregate(plan, dishes, {10: FOOD_RICE})
    assert groups[0].lines[0].quantity == "175"


def test_groups_by_category_order_and_sorts_alphabetically_case_insensitively() -> None:
    plan = plan_with([(0, Slot.LUNCH, 1), (0, Slot.DINNER, 2), (0, Slot.BREAKFAST, 3)])
    dishes = {
        1: dish_with(1, {10: 100.0}, MealType.LUNCH),
        2: dish_with(2, {11: 100.0}, MealType.DINNER),
        3: dish_with(3, {14: 1.0}, MealType.BREAKFAST),
    }
    foods = {10: FOOD_RICE, 11: FOOD_CHICKEN, 14: FOOD_APPLE}
    groups = aggregate(plan, dishes, foods)
    assert [g.category for g in groups] == [Category.PRODUCE, Category.MEAT_FISH, Category.PANTRY]


def test_sorts_foods_within_a_category_case_insensitively() -> None:
    plan = plan_with([(0, Slot.BREAKFAST, 1), (0, Slot.SNACK1, 2)])
    dishes = {
        1: dish_with(1, {14: 1.0}, MealType.BREAKFAST),
        2: dish_with(2, {15: 1.0}, MealType.SNACK),
    }
    banana = Food(id=15, name="Banana", unit=Unit.UNIT, category=Category.PRODUCE, kcal_ref=89.0)
    foods = {14: FOOD_APPLE, 15: banana}
    groups = aggregate(plan, dishes, foods)
    assert [line.food_name for line in groups[0].lines] == ["Banana", "manzana"]


def test_rounding_g_ml_and_unit() -> None:
    plan = plan_with([(0, Slot.LUNCH, 1), (0, Slot.DINNER, 2), (0, Slot.BREAKFAST, 3)])
    dishes = {
        1: dish_with(1, {10: 100.4}, MealType.LUNCH),
        2: dish_with(2, {12: 33.6}, MealType.DINNER),
        3: dish_with(3, {13: 1.27}, MealType.BREAKFAST),
    }
    foods = {10: FOOD_RICE, 12: FOOD_MILK, 13: FOOD_EGG}
    groups = aggregate(plan, dishes, foods)
    quantities = {g.category: {line.food_name: line.quantity for line in g.lines} for g in groups}
    assert quantities[Category.PANTRY]["Arroz"] == "100"
    assert quantities[Category.DAIRY_EGGS]["Leche"] == "34"
    assert quantities[Category.DAIRY_EGGS]["Huevo"] == "1.3"


def test_unit_rounding_drops_trailing_zero() -> None:
    plan = plan_with([(0, Slot.BREAKFAST, 3)])
    dishes = {3: dish_with(3, {13: 2.0}, MealType.BREAKFAST)}
    groups = aggregate(plan, dishes, {13: FOOD_EGG})
    assert groups[0].lines[0].quantity == "2"


def test_omits_empty_categories() -> None:
    plan = plan_with([(0, Slot.LUNCH, 1)])
    groups = aggregate(plan, {1: dish_with(1, {10: 100.0})}, {10: FOOD_RICE})
    assert len(groups) == 1
    assert groups[0].category == Category.PANTRY


def test_purity_calling_twice_returns_equal_and_mutates_nothing() -> None:
    plan = plan_with([(0, Slot.LUNCH, 1), (1, Slot.DINNER, 2)])
    dishes = {1: dish_with(1, {10: 100.0}), 2: dish_with(2, {11: 50.0})}
    foods = {10: FOOD_RICE, 11: FOOD_CHICKEN}
    first = aggregate(plan, dishes, foods)
    second = aggregate(plan, dishes, foods)
    assert first == second
    assert plan.entries == (
        PlanEntry(day=0, slot=Slot.LUNCH, dish_id=1),
        PlanEntry(day=1, slot=Slot.DINNER, dish_id=2),
    )


@pytest.mark.parametrize(
    ("total", "unit", "expected"),
    [
        (1.25, Unit.UNIT, "1.3"),
        (1.35, Unit.UNIT, "1.4"),
        (0.25, Unit.UNIT, "0.3"),
        (1.0, Unit.UNIT, "1"),
        (3.0, Unit.UNIT, "3"),
        (250.5, Unit.G, "251"),
        (251.5, Unit.G, "252"),
        (99.4, Unit.ML, "99"),
    ],
)
def test_quantities_round_half_up_and_predictably(total: float, unit: Unit, expected: str) -> None:
    assert _render_quantity(total, unit) == expected
