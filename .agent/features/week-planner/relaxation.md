# Week Planner — relaxation

> When the catalogue is too small to satisfy every rule, the planner loosens them in a fixed order and tells the user what it gave up, rather than failing silently or producing nothing.

## Source files

- `meal_planning_bot/planner.py` — the relaxation ladder and the `PlannerFailure` diagnosis
- `meal_planning_bot/formatting.py` — the sentence appended to a plan that needed relaxation

## Settings used

- Every key listed in `constraints.md`, read as the step-0 values

## Requirements

1. The planner shall attempt the ladder in order and shall stop at the first step that yields a plan.
2. Step 0 shall use the configured values unchanged.
3. Step 1 shall halve every `cooldown_days_<meal_type>` value, rounding down, with a floor of one day.
4. Step 2 shall set every `cooldown_days_<meal_type>` to one day, so that a dish still cannot appear on two consecutive days.
5. Step 3 shall raise `max_food_repeats_per_day` by one.
6. Step 4 shall double `kcal_tolerance_pct`.
7. The planner shall never relax the rules that a slot is filled from its own meal type and that a dish appears at most once per day. Those hold at every step.
8. The planner shall return the index of the successful step on the plan.
9. If a plan required a step above 0, then the bot shall append one sentence to the published plan naming what was relaxed.
10. If every step fails, then the planner shall return a failure listing, per meal type, the number of active dishes and the number needed, and shall state whether the calorie window is reachable at all given the lowest and highest kcal dishes available.

## Tests covering this

- `tests/test_planner.py` — each step is reached in turn by a catalogue engineered to fail the previous one; the reported step index matches; the never-relaxed rules still hold at step 4; the failure message names the short meal type and an unreachable calorie window
- `tests/test_formatting.py` — the relaxation sentence appears only when the step is above 0

## Non-goals

- A user-configurable ladder. The order is fixed in code.
- Partial plans. Either all twenty-five slots are filled or the attempt fails.
- Asking the user which rule to drop.
