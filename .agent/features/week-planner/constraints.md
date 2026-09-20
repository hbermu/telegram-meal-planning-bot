# Week Planner — constraints

> The rules a candidate plan must satisfy, and the pruning that makes the search finish.

## Source files

- `meal_planning_bot/planner.py` — `check_slot`, `day_kcal_window`, and the backtracking loop

## Settings used

- `daily_kcal_target`, `kcal_tolerance_pct`, `max_food_repeats_per_day`, `cooldown_days_breakfast`, `cooldown_days_snack`, `cooldown_days_lunch`, `cooldown_days_dinner` (settings table)

## Requirements

1. The planner shall enforce that the sum of the five dishes' kcal on each day falls within `daily_kcal_target` plus or minus `kcal_tolerance_pct` per cent, rounded to whole calories.
2. The planner shall enforce that no food appears in more than `max_food_repeats_per_day` dishes on the same day.
3. The planner shall enforce that a dish does not appear twice on the same day, including across the two snack slots.
4. The planner shall enforce, for each dish, that the gap between the day it is drawn and the most recent day it was previously served is at least `cooldown_days_<meal_type>` days, counting calendar days and treating the previous week's Friday and the current week's Monday as three days apart.
5. The planner shall apply the cooldown against both the plan being built and the served history handed to it.
6. The planner shall treat the cooldown as satisfied for a dish with no history.
7. While filling a day, the planner shall prune a partial assignment whose running kcal total plus the sum of the cheapest remaining candidates exceeds the upper bound of the day's window.
8. While filling a day, the planner shall prune a partial assignment whose running kcal total plus the sum of the dearest remaining candidates falls below the lower bound of the day's window.
9. The planner shall consider candidates for a slot in an order shuffled by the injected random source, so that the same catalogue does not always yield the same plan.
10. The planner shall fill days in order 0 to 4 and slots in order `breakfast`, `snack1`, `lunch`, `snack2`, `dinner`, backtracking to the previous slot when a day cannot be completed.
11. The planner shall count each visited node and shall abandon the attempt once the count exceeds fifty thousand.

## Tests covering this

- `tests/test_planner.py` — a catalogue whose only solution needs backtracking is solved; a food shared by three dishes never lands three times in one day at the default setting; a dish with a fourteen-day cooldown served last Wednesday cannot appear this week; the Friday-to-Monday gap counts as three days; kcal pruning rejects a day that overshoots; the node cap triggers on a deliberately hopeless catalogue

## Non-goals

- Soft constraints or weighted scoring. Every rule here is pass or fail.
- Constraints across weeks other than the cooldown.
- Balancing calories between slots. Only the daily total is budgeted.
