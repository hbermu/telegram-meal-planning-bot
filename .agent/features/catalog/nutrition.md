# Catalogue — calories

> A dish's calories are computed from its ingredients and their calorie densities, with a manual override for the cases where that is wrong. A seed file of common ingredients means the household does not have to look every number up.

## Source files

- `meal_planning_bot/nutrition.py` — `dish_kcal`, `effective_kcal`, and the seed lookup
- `meal_planning_bot/data/kcal_seed.json` — the curated ingredient table
- `meal_planning_bot/models.py` — `REFERENCE_QUANTITY`, `Food.kcal_ref`, `Dish.kcal_override`

## Settings used

none

## Requirements

1. The computed calories of a dish shall be the sum over its ingredients of `quantity / REFERENCE_QUANTITY[food.unit] * food.kcal_ref`, rounded to the nearest whole calorie.
2. If a dish carries a `kcal_override`, then its effective calories shall be that value and the computed value shall be ignored.
3. The planner and every message shall use the effective calories, never the raw computed value.
4. The seed file shall map a lower-cased Spanish ingredient name to a unit, a category, and a `kcal_ref`.
5. When a wizard asks for a new food's details and the typed name matches a seed entry exactly after lower-casing, the wizard shall offer that entry's unit, category and `kcal_ref` as the default, which the user may accept or replace.
6. If the typed name matches no seed entry, then the wizard shall ask for the unit, the category and the `kcal_ref` with no default.
7. The seed file shall be read once at startup and shall never be written to.
8. The bot shall reach no network service to obtain a calorie value.
9. If a food's `kcal_ref` changes, then dishes using it shall report their new computed calories, including in plans already generated, because a plan stores dish identifiers and not a calorie snapshot.

## Tests covering this

- `tests/test_nutrition.py` — the computation for each unit, including a `unit`-based food; rounding; the override winning over the computation; an empty override falling back to the computation
- `tests/test_wizards.py` — a seeded name pre-fills the three fields and an unseeded one does not
- `tests/test_nutrition.py` — every seed entry has a valid unit, a valid category, and a non-negative `kcal_ref`

## Non-goals

- Querying USDA FoodData Central, BEDCA, CIQUAL, Open Food Facts or any other service at runtime. The seed is generated once, offline, and committed.
- Matching an ingredient name fuzzily against the seed. An exact lower-cased match or nothing — a wrong automatic guess is worse than a question.
- Per-serving or per-person scaling.
- Macronutrients.
- Snapshotting a dish's calories into a plan so that historical plans keep their original figures.
