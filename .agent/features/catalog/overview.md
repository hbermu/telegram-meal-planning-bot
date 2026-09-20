# Catalogue

> The set of foods the household buys and the dishes built from them. The catalogue is the planner's input: only active dishes are ever drawn, and every dish resolves to the calorie figure the planner budgets against.

## Source files

- `meal_planning_bot/repo.py` — catalogue reads and writes
- `meal_planning_bot/handlers/catalog.py` — `/dishes`, `/dish`, `/foods`, `/restore`
- `meal_planning_bot/nutrition.py` — resolves each dish's effective calories for display
- `meal_planning_bot/handlers/wizards.py` — the step-by-step creation and editing flows
- `meal_planning_bot/formatting.py` — dish cards, food lists, and the paginated browser

## Settings used

none

## Requirements

1. The catalogue shall hold foods and dishes as defined in `../storage/schema.md`.
2. The catalogue shall expose only active rows to the planner and to the browsing commands.
3. When a user sends `/dishes`, the bot shall reply with the active dishes grouped by meal type, paginated at twenty per page with inline next and previous buttons.
4. When a user sends `/dish <name>`, the bot shall reply with that dish's meal type, effective calories, whether those calories are computed or overridden, ingredient list with quantities and units, and preparation steps if present.
5. If `/dish` is given a name that matches no active dish exactly, then the bot shall reply with up to five active dishes whose names contain the given text, as inline buttons.
6. When a user sends `/foods`, the bot shall reply with the active foods grouped by category, each with its unit and its `kcal_ref`.
7. When a user sends `/dishes archivados` or `/foods archivados`, the bot shall list the inactive dishes or foods, paginated the same way.
8. When a user sends `/restore <name>`, the bot shall reactivate the matching archived dish or food, and shall present inline buttons when the name matches more than one archived item.
9. If `/restore` is given a name that matches no archived item, then the bot shall say so and shall change nothing.
10. The catalogue shall report, for each meal type, how many active dishes exist, so that `../week-planner/overview.md` can explain an unsatisfiable week.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/dishes` | both | allow-listed | Paginated list of active dishes by meal type |
| `/dish <name>` | both | allow-listed | Full card for one dish, or fuzzy-match buttons |
| `/foods` | both | allow-listed | Active foods grouped by category |
| `/dishes archivados` | both | allow-listed | Inactive dishes |
| `/foods archivados` | both | allow-listed | Inactive foods |
| `/restore <name>` | private | allow-listed | Reactivate an archived dish or food |

## Tests covering this

- `tests/test_repo.py` — active filtering, per-meal-type counts, ingredient round-trips
- `tests/test_formatting.py` — dish cards render quantities with the food's unit; pagination splits at twenty; the fuzzy-match reply caps at five

## Non-goals

- Nutrition beyond calories. No macros, no micronutrients.
- Portion scaling for a number of diners. Quantities are what the household eats, full stop.
- Photos, tags, cuisines, or difficulty ratings.
- Importing dishes from a file or a website.
