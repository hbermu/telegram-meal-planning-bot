from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from meal_planning_bot.models import CATEGORY_ORDER, Category, Dish, Food, Plan, Unit


@dataclass(frozen=True)
class ShoppingLine:
    food_name: str
    quantity: str
    unit: Unit


@dataclass(frozen=True)
class ShoppingGroup:
    category: Category
    lines: tuple[ShoppingLine, ...]


def _render_quantity(total: float, unit: Unit) -> str:
    # Explicit half-up. Python's round() is half-to-even and, on binary floats, lands
    # unpredictably at ties: 1.25 goes down to 1.2 while 1.35 goes up to 1.4, and 250.5 g
    # goes down while 251.5 g goes up. A shopping list should round the way a person
    # expects, and the same way every time.
    places = Decimal("0.1") if unit is Unit.UNIT else Decimal("1")
    rounded = Decimal(str(total)).quantize(places, rounding=ROUND_HALF_UP)
    return f"{rounded.normalize():f}" if unit is Unit.UNIT else f"{rounded:f}"


def aggregate(
    plan: Plan, dishes: Mapping[int, Dish], foods: Mapping[int, Food]
) -> tuple[ShoppingGroup, ...]:
    totals: dict[int, float] = defaultdict(float)
    for entry in plan.entries:
        for ingredient in dishes[entry.dish_id].ingredients:
            totals[ingredient.food_id] += ingredient.quantity

    by_category: dict[Category, list[ShoppingLine]] = defaultdict(list)
    for food_id, total in totals.items():
        food = foods[food_id]
        by_category[food.category].append(
            ShoppingLine(
                food_name=food.name,
                quantity=_render_quantity(total, food.unit),
                unit=food.unit,
            )
        )

    groups = []
    for category in CATEGORY_ORDER:
        lines = by_category.get(category)
        if not lines:
            continue
        lines.sort(key=lambda line: line.food_name.lower())
        groups.append(ShoppingGroup(category=category, lines=tuple(lines)))
    return tuple(groups)
