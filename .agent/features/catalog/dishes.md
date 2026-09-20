# Catalogue — dishes

> A dish is one thing eaten in one slot: a name, a meal type, the foods it consumes with quantities, optional preparation steps, and calories that are computed from those ingredients unless overridden. Dish and recipe are the same entity.

## Source files

- `meal_planning_bot/models.py` — the `Dish`, `DishIngredient`, and `MealType` types
- `meal_planning_bot/nutrition.py` — `effective_kcal`
- `meal_planning_bot/repo.py` — `create_dish`, `update_dish`, `deactivate_dish`, `reactivate_dish`, `get_dish`, `list_dishes`, `count_dishes_by_meal_type`

## Settings used

none

## Requirements

1. A dish shall carry a name, one meal type of `breakfast`, `snack`, `lunch`, or `dinner`, at least one ingredient, optional free-text preparation steps, and an optional `kcal_override` greater than zero.
2. A dish's effective calories shall be resolved as defined in `nutrition.md`.
3. The repository shall match dish names case-insensitively and shall reject creating a second dish whose lower-cased name already exists.
4. The repository shall reject a dish that lists the same food twice.
5. The repository shall reject a dish with no ingredients.
6. When a dish is deactivated, the repository shall set `active = 0` and shall keep its ingredients and every plan entry referencing it.
7. When a dish is deactivated and it appears in a stored plan for the current or the following week, the repository shall return the affected day-and-slot pairs.
8. When the repository returns affected slots on deactivation, the bot shall re-draw each of them and shall report the replacements in its reply.
9. The repository shall list archived dishes on request and shall reactivate one by setting `active = 1`.
10. A dish's meal type shall be changeable, and changing it shall not alter stored plans.

## Tests covering this

- `tests/test_repo.py` — duplicate names, duplicate ingredients, empty ingredient lists, deactivation preserving history and reporting affected slots, reactivation, meal-type change not touching stored plans
- `tests/test_handlers.py` — deactivating a dish that is in the current plan re-draws its slots and names the replacements

## Non-goals

- Servings, yields, or scaling a recipe up or down.
- Rich text, images, or step-by-step timers in the preparation field.
- Deriving the meal type from the ingredients or the calories.
