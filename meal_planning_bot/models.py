from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Unit(StrEnum):
    G = "g"
    ML = "ml"
    UNIT = "unit"


# A food's kcal_ref is the calories of this much of it.
REFERENCE_QUANTITY: dict[Unit, float] = {Unit.G: 100.0, Unit.ML: 100.0, Unit.UNIT: 1.0}


class Category(StrEnum):
    PRODUCE = "produce"
    MEAT_FISH = "meat_fish"
    DAIRY_EGGS = "dairy_eggs"
    BAKERY = "bakery"
    FROZEN = "frozen"
    PANTRY = "pantry"
    DRINKS = "drinks"
    OTHER = "other"


CATEGORY_ORDER: tuple[Category, ...] = (
    Category.PRODUCE,
    Category.MEAT_FISH,
    Category.DAIRY_EGGS,
    Category.BAKERY,
    Category.FROZEN,
    Category.PANTRY,
    Category.DRINKS,
    Category.OTHER,
)


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    SNACK = "snack"
    LUNCH = "lunch"
    DINNER = "dinner"


class Slot(StrEnum):
    BREAKFAST = "breakfast"
    SNACK1 = "snack1"
    LUNCH = "lunch"
    SNACK2 = "snack2"
    DINNER = "dinner"


SLOT_ORDER: tuple[Slot, ...] = (
    Slot.BREAKFAST,
    Slot.SNACK1,
    Slot.LUNCH,
    Slot.SNACK2,
    Slot.DINNER,
)

SLOT_MEAL_TYPE: dict[Slot, MealType] = {
    Slot.BREAKFAST: MealType.BREAKFAST,
    Slot.SNACK1: MealType.SNACK,
    Slot.LUNCH: MealType.LUNCH,
    Slot.SNACK2: MealType.SNACK,
    Slot.DINNER: MealType.DINNER,
}


@dataclass(frozen=True)
class Food:
    id: int
    name: str
    unit: Unit
    category: Category
    kcal_ref: float
    active: bool = True


@dataclass(frozen=True)
class DishIngredient:
    food_id: int
    quantity: float


@dataclass(frozen=True)
class Dish:
    id: int
    name: str
    meal_type: MealType
    kcal: int  # effective: the override when set, else computed
    ingredients: tuple[DishIngredient, ...]
    kcal_override: int | None = None
    steps: str | None = None
    active: bool = True


@dataclass(frozen=True)
class PlanEntry:
    day: int
    slot: Slot
    dish_id: int


@dataclass(frozen=True)
class Plan:
    week_start: date
    entries: tuple[PlanEntry, ...]
    relaxation: int = 0


@dataclass(frozen=True)
class ServedRecord:
    dish_id: int
    served_on: date


# `kcal` is resolved by repo.py when a Dish is loaded, so planner.py never needs the
# food table and stays a pure function of its arguments. `kcal_override` is kept only
# so formatting can say whether the figure was computed or typed.


@dataclass(frozen=True)
class PlannerSettings:
    daily_kcal_target: int
    kcal_tolerance_pct: int
    max_food_repeats_per_day: int
    cooldown_days: Mapping[MealType, int]
