# Catalogue — wizards

> Adding a dish from a phone is a conversation, not a syntax. Each mutating command walks the user through one question at a time in a private chat and writes nothing until the final confirmation.

## Source files

- `meal_planning_bot/handlers/wizards.py` — the conversation handlers and their states
- `meal_planning_bot/formatting.py` — every prompt, summary, and error string
- `meal_planning_bot/repo.py` — `create_dish_with_new_foods` and `update_dish_ingredients_with_new_foods`, which write the dish and any inline-created foods in one transaction

## Settings used

none

## Requirements

1. The wizards shall run only in a private chat, enforced by `../access-control/overview.md`.
2. While a wizard is in progress, the bot shall treat plain text messages from that user as answers to the current step.
3. The bot shall allow only one wizard per user at a time, and starting a second shall replace the first with a notice that the previous one was discarded.
4. When a user sends `/cancel`, the bot shall discard the in-progress wizard and write nothing.
5. The `/newdish` wizard shall ask, in order: name, meal type (inline buttons), then ingredients one at a time, then preparation steps, then whether to accept the computed calories or enter an override.
6. While collecting ingredients, the wizard shall accept a food name followed by a quantity, and shall offer a `Done` button once at least one ingredient has been added.
7. If a food name given during ingredient collection matches no active food, then the wizard shall offer to create it inline by asking for its unit, category and `kcal_ref`, pre-filled from the seed file when the name matches an entry as defined in `nutrition.md`, and shall then continue the ingredient step.
8. If a food name given during ingredient collection matches several active foods by substring, then the wizard shall present up to five as inline buttons rather than guessing.
9. The wizard shall reject a quantity that is not a positive number and shall re-ask the same step.
10. The preparation step shall accept a `Skip` button that stores no steps.
10b. The calorie step shall show the value computed from the ingredients and shall offer an `Accept` button storing no override, or a typed number storing one.
11. Before writing, the wizard shall show a summary card of the dish, including its effective calories and whether they are computed or overridden, and shall require a `Confirm` or `Discard` choice.
12. When the user confirms, the bot shall write the dish, its ingredients, and any inline-created foods in a single transaction, through `repo.create_dish_with_new_foods`. Composing `repo.create_food` and `repo.create_dish` would not satisfy this: each commits its own transaction, so a dish rejected for a duplicate name would leave the inline-created food behind.
13. The `/editdish` wizard shall first resolve a dish by name, then present inline buttons for the field to change, then run only that field's step, then confirm.
14. The `/deletedish` and `/deletefood` wizards shall resolve the target by name and shall require an explicit confirmation before deactivating it.
15. If the bot restarts while a wizard is in progress, then that wizard shall be lost and the next message from the user shall be handled as a normal command.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/newdish` | private | allow-listed | Creates a dish, creating foods inline as needed |
| `/editdish` | private | allow-listed | Changes one field of an existing dish |
| `/deletedish` | private | allow-listed | Deactivates a dish after confirmation |
| `/newfood` | private | allow-listed | Creates a food: name, unit, category, kcal_ref |
| `/editfood` | private | allow-listed | Changes a food's name, unit, category or kcal_ref |
| `/deletefood` | private | allow-listed | Deactivates an unreferenced food after confirmation |
| `/cancel` | private | allow-listed | Discards the in-progress wizard |

## Tests covering this

- `tests/test_wizards.py` — the state machine driven by synthetic updates: full happy path for `/newdish`, inline food creation, ambiguous food name, invalid quantity re-asks, `/cancel` writes nothing, a second wizard replaces the first, discard at the summary writes nothing
- `tests/test_repo.py` — the confirmation write is one transaction: a failure part-way leaves no food and no dish

## Non-goals

- One-line syntax commands such as `/dish name | type | kcal | ingredients`.
- Persisting wizard state across restarts.
- Bulk import from a file.
- Editing several fields in one `/editdish` run.
