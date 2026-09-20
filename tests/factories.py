from collections.abc import Sequence

from meal_planning_bot.models import Dish, DishIngredient, MealType, PlannerSettings

DEFAULT_SETTINGS = PlannerSettings(
    daily_kcal_target=2000,
    kcal_tolerance_pct=10,
    max_food_repeats_per_day=2,
    cooldown_days={
        MealType.BREAKFAST: 1,
        MealType.SNACK: 1,
        MealType.LUNCH: 14,
        MealType.DINNER: 1,
    },
)


def dish(id: int, meal_type: MealType, kcal: int, foods: Sequence[int] = ()) -> Dish:
    return Dish(
        id=id,
        name=f"d{id}",
        meal_type=meal_type,
        kcal=kcal,
        ingredients=tuple(DishIngredient(food_id=f, quantity=100.0) for f in foods),
    )


def catalogue(per_type: int, kcal: dict[MealType, int]) -> list[Dish]:
    out: list[Dish] = []
    next_id = 1
    for meal_type in MealType:
        for _ in range(per_type):
            out.append(dish(next_id, meal_type, kcal[meal_type], foods=[next_id]))
            next_id += 1
    return out
