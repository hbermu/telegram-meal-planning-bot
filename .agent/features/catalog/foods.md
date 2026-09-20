# Catalogue — foods

> A food is a purchasable ingredient with exactly one unit, one supermarket category, and a calorie density. Foods let the shopping list add quantities together, group them by aisle, and let a dish's calories be computed instead of guessed.

## Source files

- `meal_planning_bot/models.py` — the `Food` dataclass, the `Unit` and `Category` enums, and `REFERENCE_QUANTITY`
- `meal_planning_bot/repo.py` — `create_food`, `update_food`, `deactivate_food`, `reactivate_food`, `find_foods_by_name`, `list_foods`

## Settings used

none

## Requirements

1. A food shall carry a name, one unit of `g`, `ml`, or `unit`, one category of `produce`, `meat_fish`, `dairy_eggs`, `bakery`, `frozen`, `pantry`, `drinks`, or `other`, and a `kcal_ref` value greater than or equal to zero.
2. The `kcal_ref` value shall be the calories of the food's reference quantity, where the reference quantity is 100 for units `g` and `ml` and 1 for unit `unit`, as defined by `REFERENCE_QUANTITY` in `models.py`.
3. The repository shall match food names case-insensitively and shall reject creating a second food whose lower-cased name already exists.
4. The repository shall store food names with the capitalisation the user typed.
5. When a food's unit is changed, the repository shall leave existing `dish_ingredients` quantities untouched and shall require a new `kcal_ref`, because the reference quantity changes with the unit.
6. If a food is referenced by any dish, then deactivating it shall be refused with the list of referencing dish names.
7. The repository shall list archived foods on request and shall reactivate one by setting `active = 1`.
8. The category order used for grouping shall be `produce`, `meat_fish`, `dairy_eggs`, `bakery`, `frozen`, `pantry`, `drinks`, `other`, matching the order the aisles are walked.

## Tests covering this

- `tests/test_repo.py` — case-insensitive duplicate rejection, capitalisation preserved, deactivation refused while referenced, reactivation, unit change leaving quantities alone and demanding a new `kcal_ref`
- `tests/test_formatting.py` — the category grouping order

## Non-goals

- Unit conversion. A food has one unit at a time; changing it rescales nothing.
- Nutrients other than calories. No macros, no micronutrients.
- Brands, prices, shops, or stock levels.
- Substitutions or "equivalent food" relationships.
- Looking a food up in an online nutrition service at runtime. See `nutrition.md`.
