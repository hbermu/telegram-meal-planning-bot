# Week Planner — partial plans

> An opt-in mode that lets the planner draw only the meal types the catalogue can actually support, instead of refusing to draw anything until all four are stocked. A household that has typed in its lunches but no breakfasts gets its lunches planned, with the rest of each day left blank and named as missing.

## Source files

- `meal_planning_bot/config.py` — reads and validates the switch
- `meal_planning_bot/planner.py` — `eligible_slots`, the slot-driven search space, and the dropped calorie floor
- `meal_planning_bot/formatting.py` — omits the unplanned slots and names the missing meal types
- `meal_planning_bot/handlers/plan.py` — passes the switch to the planner on `/regenerate`, and refuses `/swap` on an unplanned slot
- `meal_planning_bot/scheduler.py` — passes the switch to the planner on the weekly job, the daily job and the startup catch-up

## Settings used

- `MEALBOT_ALLOW_PARTIAL_PLAN` (environment) — whether a plan may cover fewer than the five slots, default `false`

## Requirements

1. The bot shall accept `MEALBOT_ALLOW_PARTIAL_PLAN` as one of `true`, `false`, `1`, `0`, `yes` or `no`, case-insensitively, and shall default it to `false`.
2. If `MEALBOT_ALLOW_PARTIAL_PLAN` holds any other value, then the bot shall refuse to start and shall name the variable.
3. While `MEALBOT_ALLOW_PARTIAL_PLAN` is false, the planner shall draw all five slots or shall fail, which is the behaviour described in `overview.md`.
4. While `MEALBOT_ALLOW_PARTIAL_PLAN` is true, the planner shall draw only the slots whose meal type has at least as many active dishes as there are positions for that meal type in a week: five for `breakfast`, five for `lunch`, five for `dinner`, and ten for `snack`.
5. The planner shall decide eligibility per meal type, so `snack1` and `snack2` are always both drawn or both omitted.
6. The planner shall count only active dishes when deciding eligibility, so archiving a dish can take its meal type out of the plan.
7. When a plan covers fewer than five slots, the planner shall enforce only the upper bound of the day's calorie window and shall drop the lower bound, because a day that is missing meals cannot reach `daily_kcal_target`.
8. A partial plan shall satisfy every other hard constraint in `constraints.md` unchanged, and shall use the relaxation ladder in `relaxation.md` unchanged.
9. If no meal type has enough active dishes, then the planner shall fail with the same diagnosis it gives in full mode, naming every meal type that is short.
10. When rendering a plan, the bot shall omit the line of every slot the plan does not cover, and shall total only the slots it does cover.
11. When a plan covers fewer than four meal types, the bot shall close the weekly plan message with one line naming the missing meal types, so a reader knows the gap is a thin catalogue and not a fault.
12. The bot shall not add that line to the daily message, which covers one day and is read as a reminder rather than as a report.
13. If `/swap` names a slot the stored plan does not cover, then the bot shall say so, shall point at `/newdish` and `/regenerate`, and shall change nothing.
14. The planner shall read which slots a stored plan covers from the plan's own entries, so re-drawing one slot needs no knowledge of the switch.
15. A plan already stored shall not change when the switch changes; `/regenerate` is what redraws a week under the current setting.

## Tests covering this

- `tests/test_config.py` — the default is false; each accepted spelling parses; an unparseable value is rejected naming the variable
- `tests/test_planner.py` — `eligible_slots` returns all five slots for a ten-per-type catalogue and drops `snack1`/`snack2` for a six-per-type one; each meal type's threshold is exact at one dish below and at the threshold; an archived dish takes its meal type out; a lunch-only catalogue yields five lunch entries with the switch on and still fails with it off; the floor is dropped but the ceiling of the loosest relaxation rung still fails a plan; a partial plan keeps the dish-repeat and cooldown rules and honours history; an empty catalogue fails naming all four meal types; `/swap` on a slot the plan never drew raises, and a slot it did draw still re-draws
- `tests/test_planner_invariants.py` — a sweep over catalogues starved of whole meal types: every returned partial plan satisfies the full invariant set over the slots it covers, and a guard asserts the sweep returns plans rather than failing throughout
- `tests/test_formatting.py` — a lunch-only plan shows no breakfast, snack or dinner line, totals only the lunch, and carries the missing-meal-type line; a full plan carries no such line; the daily message omits the unplanned slots and carries no such line
- `tests/test_handlers.py` — `/regenerate` with the switch on saves a lunch-only plan and replies with the missing-meal-type line; `/swap` on an unplanned slot replies and leaves the stored plan untouched
- `tests/test_scheduler.py` — the weekly job posts a partial plan and its shopping list instead of a diagnosis, still posts the diagnosis with the switch off, and the startup catch-up draws a partial week

## Non-goals

- A per-slot calorie quota. There is no "a lunch should be 35 per cent of the day"; the day is budgeted as a whole or, when partial, only capped.
- Choosing the covered meal types by hand. Eligibility is derived from the catalogue, never configured.
- A per-meal-type switch. The mode is on or off for the whole plan.
- Lowering the thresholds. A meal type that cannot fill its week's positions with distinct dishes stays out rather than repeating one dish all week.
- Changing a stored plan in place when the catalogue grows. The next `/regenerate` picks the new meal types up.
