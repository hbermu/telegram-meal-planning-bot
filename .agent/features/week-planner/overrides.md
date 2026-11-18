# Week Planner — overrides

> Choosing by hand what one slot is, instead of letting the draw decide: a dish from the catalogue, or a note — a dish typed by hand that the catalogue does not have, or a slot nobody is cooking. The chosen slot is pinned — re-drawing the week keeps it and draws the rest of the week around it — and the bot obeys it even when it breaks a constraint, saying so rather than refusing.

## Source files

- `meal_planning_bot/handlers/override.py` — `/override`, its argument grammar, the button flow, and the typed custom dish
- `meal_planning_bot/__main__.py` — routes plain text to a waiting custom-dish prompt before any wizard
- `meal_planning_bot/handlers/wizards.py` — starting a wizard forgets a waiting custom-dish prompt
- `meal_planning_bot/planner.py` — `Pinned`, `pin`, the pinned branch of the search, `apply_overrides`, `covered_slots`, `days_outside_window`
- `meal_planning_bot/models.py` — `PlanEntry`'s `note` and `override`
- `meal_planning_bot/repo.py` — persists the two columns and reads back a week's pinned entries with `plan_overrides`
- `meal_planning_bot/formatting.py` — the mark on a chosen slot, the calorie warning, the button labels, the custom-dish prompt
- `meal_planning_bot/handlers/keyboards.py` — the plan menu's entry into the flow

## Settings used

- `daily_kcal_target`, `kcal_tolerance_pct` (settings table) — the window a pinned slot may push a day out of

## Requirements

1. A plan entry shall carry either a dish or a note, never both and never neither.
2. An entry a user chose by hand shall be marked as such, and a note shall only ever exist on such an entry.
3. When a user sends `/override` with a day, a slot and the name of an active dish, the bot shall pin that dish to that slot.
4. When a user sends `/override` with a day, a slot and the keyword `fuera`, the bot shall pin a note to that slot, taking the rest of the line as the note and `Fuera` when nothing follows.
5. The `/override` command shall accept a day as `lunes` through `viernes`, as 1–5, or as `hoy` or `mañana`, and a slot as `desayuno`, `snack1`, `comida`, `snack2` or `cena`.
6. The `/override` command shall accept the keyword `siguiente` as its first argument to address next week, because what follows the slot is free text and a trailing keyword could not be told apart from it.
7. If `/override` is given `hoy` or `mañana` together with `siguiente`, then the bot shall reply with the accepted forms and shall change nothing.
8. If `hoy` or `mañana` names a Saturday or a Sunday, then the bot shall say that the weekend is not planned and shall change nothing.
9. If the name given to `/override` matches no active dish, then the bot shall say so and shall change nothing. A name nobody recognises is a typo, not a decision to eat out, and shall never be stored as a note.
10. If the name given to `/override` matches several active dishes and none of them exactly, then the bot shall offer them as inline buttons.
11. When `/override` names a slot the stored plan does not cover, the bot shall add the chosen entry to that day, so what was eaten counts in the day's total, the shopping list and the cooldown history even where the catalogue is too thin to draw the slot.
12. If no plan exists for the addressed week, then `/override` shall say so and shall suggest `/regenerate`.
13. The bot shall accept a pinned dish whose meal type does not match the slot, because an override records a decision rather than asking for one.
14. When a week is re-drawn, the planner shall hold every pinned entry of that week and shall draw the remaining slots around it, charging the day for the pinned entry's calories and its ingredients.
14b. When a week is re-drawn, the planner shall lay every pinned entry on a slot the draw does not cover back on its day after the draw, without charging the draw for it.
15. The planner shall apply no constraint from `constraints.md` to a pinned entry.
16. While a day holds a note, the planner shall drop that day's lower calorie bound and shall keep its ceiling, for the same reason `partial-plans.md` drops it.
17. If no relaxation step can draw a week around the pinned entries, then the planner shall draw the week without them and lay them back over the result, so that an override can never make a week undrawable.
18. When a pinned entry leaves its day outside the calorie window, the bot shall say which day, and shall still store the plan.
19. A note shall contribute nothing to the shopping list and nothing to the cooldown history, because nobody cooks it and no dish was served.
20. When a pinned slot is re-drawn with `/swap`, the bot shall release it: the new entry is a drawn one, and that is how an override is undone. On a slot the plan does not cover, releasing it removes the entry and leaves the slot empty again.
21. A rendered day shall mark every slot that was chosen by hand, and shall show a note without calories and outside the day's total.
22. When a user sends `/override` with no arguments, or taps the plan menu's change button, the bot shall walk the choice with buttons: a day, then a slot, then what to eat.
23. If `/override` is sent with no arguments and no plan exists for the current week, then the bot shall say so and shall suggest `/regenerate`.
24. The day step shall offer Monday to Friday, and while it addresses the current week on a weekday it shall offer `Hoy` above them as the first button.
25. The dish step shall show the active dishes of the slot's meal type in a grid of two columns and at most six rows, led by a custom-dish button, with a previous-page and a next-page button below the grid whenever there is a page that way, and a back button to the slot step.
26. If a dish-step button names a page past the last one, then the bot shall show the last page.
27. When the custom-dish button is tapped, the bot shall ask for the dish as text, with a back button to the dish step, and the next text message that user sends in that chat shall be pinned to the slot as a note.
28. The custom-dish prompt shall ask for a reply to it in a group, because a bot in a group may only see messages that reply to it.
29. The slot step shall offer all five slots, whether or not the plan covers them.
30. When the user taps any button of the flow or starts a wizard while the custom-dish prompt waits, the bot shall forget the prompt, so that a later message is never pinned by mistake.
31. The custom-dish prompt shall be held in memory only, like a wizard, so a restart forgets it.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/override` | both | allow-listed | Asks for the day, the slot and the dish with buttons |
| `/override [siguiente] <day> <slot> <dish>` | both | allow-listed | Pins that dish to that slot |
| `/override [siguiente] <day> <slot> fuera [text]` | both | allow-listed | Pins a note to that slot |

## Tests covering this

- `tests/test_planner.py` — a pinned dish survives the draw; it is obeyed against the cooldown; the rest of the day is drawn around it; a note drops the day's floor; a pin no week can hold is laid on top instead of refused; a pin on a slot the draw skips is added to its day and survives the draw; `apply_overrides` replaces drawn entries and adds the rest; re-drawing a pin on a skipped slot removes it; `days_outside_window` names the day a pin pushed out; re-drawing a pinned slot releases it
- `tests/test_repo.py` — a hand-picked entry round-trips; `plan_overrides` returns only the pinned entries; a note is no part of the cooldown history
- `tests/test_migrations.py` — migration 2 keeps existing entries as drawn; an entry cannot carry both a dish and a note, or neither; a note cannot exist on a drawn entry
- `tests/test_handlers.py` — the argument grammar in words, numbers, `hoy`, `mañana` and `siguiente`; the `fuera` keyword with and without text; a weekend relative day; an unknown name; an ambiguous name; a slot the plan does not cover is filled, survives `/regenerate`, keeps the partial-plan line, and `/swap` takes it off; every slot offered as a button; no plan; the calorie warning; a pin surviving `/regenerate`; `/swap` releasing it; the button flow from a day to a dish; `/override` alone opens it with `Hoy` first, and without a plan says so; `Hoy` only on a weekday of the current week; the two-by-six dish grid led by the custom button, its paging and a page past the last; the custom button pins the next text in that chat and nothing in another chat; a tap or a wizard forgets the prompt
- `tests/test_shopping.py` — a slot nobody cooks buys nothing
- `tests/test_formatting.py` — a hand-picked slot is marked and a note carries no calories
- `tests/test_integration.py` — a hand-picked meal reaches the plan, the shopping list and the next draw; a custom dish typed into the button flow in a group is pinned in place, its message is deleted, and the next message is left alone

## Non-goals

- Pinning a whole day or a whole week. One slot at a time.
- Re-balancing the other days to make up for a pinned slot's calories.
- Recording what was actually eaten afterwards. An override is a decision in advance, not a log.
- Teaching the catalogue from a note. A note is text, and `/newdish` is how a dish is added.
