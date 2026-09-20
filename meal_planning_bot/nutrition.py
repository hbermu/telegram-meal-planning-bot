import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from meal_planning_bot.models import REFERENCE_QUANTITY, Category, DishIngredient, Food, Unit


@dataclass(frozen=True)
class SeedEntry:
    unit: Unit
    category: Category
    kcal_ref: float


@cache
def _seed() -> dict[str, SeedEntry]:
    raw = json.loads(files("meal_planning_bot.data").joinpath("kcal_seed.json").read_text("utf-8"))
    return {
        name.lower(): SeedEntry(Unit(e["unit"]), Category(e["category"]), float(e["kcal_ref"]))
        for name, e in raw.items()
    }


def seed_lookup(name: str) -> SeedEntry | None:
    return _seed().get(name.strip().lower())


def computed_kcal(ingredients: Sequence[DishIngredient], foods: Mapping[int, Food]) -> int:
    total = 0.0
    for ingredient in ingredients:
        food = foods[ingredient.food_id]
        total += ingredient.quantity / REFERENCE_QUANTITY[food.unit] * food.kcal_ref
    return round(total)


def effective_kcal(
    ingredients: Sequence[DishIngredient],
    foods: Mapping[int, Food],
    override: int | None,
) -> int:
    return override if override is not None else computed_kcal(ingredients, foods)
