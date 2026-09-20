from dataclasses import replace
from datetime import date
from pathlib import Path

from meal_planning_bot.formatting import (
    COMMANDS,
    DAY_LABELS,
    SLOT_LABELS,
    render_day,
    render_dish,
    render_dishes_page,
    render_help,
    render_plan,
    render_relaxation_notice,
    render_shopping,
)
from meal_planning_bot.models import (
    SLOT_MEAL_TYPE,
    SLOT_ORDER,
    Category,
    Dish,
    DishIngredient,
    Food,
    MealType,
    Plan,
    PlanEntry,
    Unit,
)
from meal_planning_bot.shopping import ShoppingGroup, ShoppingLine


def _dish(id: int, name: str, meal_type: MealType, kcal: int) -> Dish:
    return Dish(id=id, name=name, meal_type=meal_type, kcal=kcal, ingredients=())


def _full_week_plan() -> tuple[Plan, dict[int, Dish]]:
    dishes: dict[int, Dish] = {}
    entries: list[PlanEntry] = []
    next_id = 1
    for day in range(5):
        for slot in SLOT_ORDER:
            meal_type = SLOT_MEAL_TYPE[slot]
            d = _dish(next_id, f"Plato{next_id}", meal_type, 300 + next_id)
            dishes[next_id] = d
            entries.append(PlanEntry(day=day, slot=slot, dish_id=next_id))
            next_id += 1
    plan = Plan(week_start=date(2026, 9, 21), entries=tuple(entries))
    return plan, dishes


def test_render_plan_shows_five_days_five_slots_and_totals() -> None:
    plan, dishes = _full_week_plan()
    text = render_plan(plan, dishes, is_next_week=False)
    for label in DAY_LABELS:
        assert label in text
    for slot_label in SLOT_LABELS.values():
        assert text.count(slot_label) == 5
    assert text.count("Total:") == 5


def test_render_plan_names_next_week() -> None:
    plan, dishes = _full_week_plan()
    current = render_plan(plan, dishes, is_next_week=False)
    upcoming = render_plan(plan, dishes, is_next_week=True)
    assert current != upcoming
    assert "21/09" in upcoming


def test_render_day_shows_one_days_five_slots() -> None:
    plan, dishes = _full_week_plan()
    text = render_day(plan, dishes, day=0)
    for slot_label in SLOT_LABELS.values():
        assert slot_label in text
    assert "Lunes" in text
    assert "Martes" not in text


def _big_group(category: Category, count: int) -> ShoppingGroup:
    lines = tuple(
        ShoppingLine(food_name=f"Alimento{i:04d}", quantity="100", unit=Unit.G)
        for i in range(count)
    )
    return ShoppingGroup(category=category, lines=lines)


def test_shopping_splits_at_a_category_boundary() -> None:
    groups = (
        _big_group(Category.PRODUCE, 150),
        _big_group(Category.MEAT_FISH, 150),
    )
    messages = render_shopping(groups)
    assert len(messages) > 1
    assert all(len(m) <= 4000 for m in messages)
    assert not any(m.startswith("  ") for m in messages)


def test_shopping_splits_a_single_oversized_category() -> None:
    groups = (_big_group(Category.PRODUCE, 400),)
    messages = render_shopping(groups)
    assert len(messages) > 1
    assert all(len(m) <= 4000 for m in messages)
    assert not any(m.startswith("  ") for m in messages)


def test_shopping_small_list_is_one_message() -> None:
    groups = (_big_group(Category.PRODUCE, 2),)
    messages = render_shopping(groups)
    assert len(messages) == 1
    assert "Frutas y verduras" in messages[0]
    assert "Alimento0000" in messages[0]


def test_render_dish_states_computed_or_overridden() -> None:
    food = Food(id=1, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    computed = Dish(
        id=1,
        name="Arroz blanco",
        meal_type=MealType.LUNCH,
        kcal=200,
        ingredients=(DishIngredient(food_id=1, quantity=150.0),),
    )
    overridden = replace(computed, id=2, kcal_override=250, kcal=250)
    computed_text = render_dish(computed, {1: food})
    overridden_text = render_dish(overridden, {1: food})
    assert "calculadas" in computed_text
    assert "calculadas" not in overridden_text
    assert "manual" in overridden_text
    assert "150" in computed_text
    assert "Arroz" in computed_text


def test_render_dish_includes_steps_when_present() -> None:
    food = Food(id=1, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    dish = Dish(
        id=1,
        name="Arroz",
        meal_type=MealType.LUNCH,
        kcal=200,
        ingredients=(DishIngredient(food_id=1, quantity=150.0),),
        steps="Hervir 15 minutos.",
    )
    text = render_dish(dish, {1: food})
    assert "Hervir 15 minutos." in text


def test_render_dish_omits_steps_when_absent() -> None:
    food = Food(id=1, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=130.0)
    dish = Dish(
        id=1,
        name="Arroz",
        meal_type=MealType.LUNCH,
        kcal=200,
        ingredients=(DishIngredient(food_id=1, quantity=150.0),),
    )
    text = render_dish(dish, {1: food})
    assert "Preparaci" not in text


def test_render_dishes_page_paginates_at_twenty_and_reports_page() -> None:
    dishes = [
        Dish(id=i, name=f"Plato{i}", meal_type=MealType.LUNCH, kcal=100, ingredients=())
        for i in range(1, 26)
    ]
    page1 = render_dishes_page(dishes, page=1)
    page2 = render_dishes_page(dishes, page=2)
    assert "Página 1 de 2" in page1
    assert "Página 2 de 2" in page2
    assert page1.count("Plato") == 20
    assert page2.count("Plato") == 5


def test_render_relaxation_notice_empty_at_step_zero() -> None:
    assert render_relaxation_notice(0) == ""


def test_render_relaxation_notice_nonempty_above_zero_and_distinct() -> None:
    texts = {step: render_relaxation_notice(step) for step in range(1, 5)}
    assert all(texts.values())
    assert len(set(texts.values())) == 4


def test_render_help_lists_every_command() -> None:
    text = render_help()
    for command in COMMANDS:
        assert command.usage in text
        assert command.description in text


def test_spanish_lives_only_in_formatting() -> None:
    for path in Path("meal_planning_bot").rglob("*.py"):
        if path.name == "formatting.py":
            continue
        for line in path.read_text().splitlines():
            stripped = line.split("#", 1)[0]
            assert stripped.isascii(), f"non-ASCII literal in {path}: {line}"
