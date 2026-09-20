# Week Planner

> Draws a Monday-to-Friday menu at random from the active catalogue: five days, five slots each, under a daily calorie budget and variety rules. The solver is pure — a catalogue, the recent history, the settings and a seeded random source in, a plan out.

## Source files

- `meal_planning_bot/planner.py` — the solver, the constraint checks, and the relaxation ladder
- `meal_planning_bot/models.py` — `PlanDraft`, `PlanEntry`, `SlotCandidates`, `PlannerFailure`
- `meal_planning_bot/repo.py` — loads the catalogue and the recent history, persists the result
- `meal_planning_bot/handlers/plan.py` — `/plan`, `/regenerate`, `/swap`
- `meal_planning_bot/weeks.py` — resolves the `siguiente` keyword to next Monday's `week_start`

## Settings used

- `daily_kcal_target` (settings table) — target calories per day
- `kcal_tolerance_pct` (settings table) — allowed deviation from the target, per cent
- `max_food_repeats_per_day` (settings table) — how many dishes in one day may share a food
- `cooldown_days_breakfast`, `cooldown_days_snack`, `cooldown_days_lunch`, `cooldown_days_dinner` (settings table) — minimum gap before a dish of that meal type may be drawn again

## Requirements

1. The planner shall produce exactly one dish for each of the twenty-five pairs of day 0–4 and slot `breakfast`, `snack1`, `lunch`, `snack2`, `dinner`.
2. The planner shall draw each slot only from active dishes whose meal type matches the slot, where both `snack1` and `snack2` match meal type `snack`.
3. The planner shall satisfy every hard constraint in `constraints.md` or shall relax them in the order given in `relaxation.md`.
4. The planner shall take a `random.Random` instance as an argument and shall use no other source of randomness, so that a given seed and catalogue always produce the same plan.
5. The planner shall not import `sqlite3`, `telegram`, or the current time.
6. The planner shall receive the history it needs as an explicit list of dish-and-date pairs, not as a database handle.
7. The planner shall record on the produced plan which relaxation step succeeded, as an integer where 0 means no constraint was relaxed.
8. If no relaxation step yields a plan, then the planner shall return a failure that names the blocking cause: the meal types with too few active dishes, or that the calorie window cannot be reached given the cheapest and dearest dishes available.
9. The planner shall abandon a relaxation step after a bounded number of search node visits and move to the next step rather than run unbounded.
10. When a plan is regenerated for a week that already has one, the repository shall replace the existing plan's entries rather than create a second plan for the same `week_start`.
10b. The planner shall be able to draw any `week_start`, and the commands shall address either the current week or the following one through the optional keyword `siguiente`.
11. When one slot is re-drawn, the planner shall hold the other twenty-four assignments fixed and shall apply the same hard constraints to the candidate.
12. If re-drawing one slot has no valid candidate, then the bot shall say so and shall leave the existing assignment in place.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/plan [siguiente]` | both | allow-listed | Shows this week's plan, or next week's |
| `/regenerate [siguiente]` | both | allow-listed | Draws a new plan for that week and re-renders the shopping list |
| `/swap <day> <slot> [siguiente]` | both | allow-listed | Re-draws one slot, keeping the rest |

## Tests covering this

- `tests/test_planner.py` — a solvable catalogue fills all twenty-five slots; the same seed reproduces the same plan; each hard constraint holds in the result; each relaxation step is reached in order; the node cap ends a hopeless search; a catalogue short on dinners fails with dinner named; single-slot re-draw keeps the other assignments and honours the constraints
- `tests/test_repo.py` — regenerating a week replaces its entries instead of duplicating the plan row

## Non-goals

- Optimising for anything. The first plan that satisfies the constraints wins; there is no score and no "best" plan.
- Leftovers, batch cooking, or carrying a dish from lunch to the next day's dinner.
- Weekends. Saturday and Sunday are never planned.
- Planning further than one week ahead. `siguiente` is the limit.
- Marking a slot as eaten out. Every slot is cooked and shopped for; see `../shopping-list/overview.md`.
- Per-person plans. There is one plan for the household.
- Seasonality, cost, or prep time as constraints.
