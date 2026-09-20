# Shopping List

> Adds up every ingredient across the twenty-five dishes of a week and presents the totals grouped by supermarket category, so one message covers the whole shop.

## Source files

- `meal_planning_bot/shopping.py` — the pure aggregation
- `meal_planning_bot/formatting.py` — the grouped message
- `meal_planning_bot/handlers/plan.py` — `/shopping`

## Settings used

none

## Requirements

1. The aggregation shall take a plan's dishes with their ingredients and shall return one line per food with the summed quantity and that food's unit.
2. The aggregation shall add a food's quantity once per dish occurrence, so a dish drawn on two days contributes twice.
3. The aggregation shall group foods by category in the order defined in `../catalog/foods.md`.
4. The aggregation shall sort foods alphabetically within a category, case-insensitively.
5. The aggregation shall round a summed quantity to the nearest whole number for units `g` and `ml`, and to one decimal place for unit `unit`, dropping a trailing `.0`.
5b. The aggregation shall round halves away from zero, so that a tie rounds the way a reader expects and rounds the same way every time. The language's default half-to-even rounding is not acceptable here: on binary floats it sends 1.25 down and 1.35 up.
6. The aggregation shall omit a category that has no foods.
7. The aggregation shall be pure: same plan in, same list out, with no database or clock access.
8. When a user sends `/shopping`, the bot shall reply with the list for the current week's plan, or for next week's when given the keyword `siguiente`.
9. If no plan exists for the current week, then `/shopping` shall say so and shall suggest `/regenerate`.
10. When a plan is regenerated or a slot is swapped, the next `/shopping` shall reflect the change, because the list is derived and never stored.
11. If the rendered list exceeds the Telegram message length limit, then the bot shall split it at a category boundary across several messages.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/shopping [siguiente]` | both | allow-listed | The aggregated shopping list for that week |

## Tests covering this

- `tests/test_shopping.py` — half-up rounding pinned at the ties for every unit; a food used by three dishes sums across them; a dish drawn twice counts twice; category order and alphabetical order within a category; rounding for each unit; empty categories omitted; purity, by calling twice and comparing
- `tests/test_formatting.py` — splitting at a category boundary when over the length limit

## Non-goals

- Pantry awareness. The list assumes nothing is already at home.
- Excluding meals the household will eat out. There is no way to skip a slot, so a week with a restaurant dinner over-buys for it. Accepted deliberately.
- Checkboxes, tick-off state, or exporting to a shopping app.
- Prices, shops, or quantities rounded to package sizes.
- Storing the list. It is always derived from the plan.
