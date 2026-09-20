# Command Surface

> Every command the bot answers, where it may be used, and how it replies when something is missing. The command list is a contract: it is registered with Telegram at startup so the client shows it.

## Source files

- `meal_planning_bot/__main__.py` — handler registration and the `setMyCommands` call
- `meal_planning_bot/handlers/help.py` — `/start`, `/help`
- `meal_planning_bot/handlers/plan.py` — `/plan`, `/today`, `/shopping`, `/regenerate`, `/swap`
- `meal_planning_bot/handlers/catalog.py` — `/dishes`, `/dish`, `/foods`, `/restore`
- `meal_planning_bot/weeks.py` — resolves the `siguiente` keyword
- `meal_planning_bot/handlers/wizards.py` — the mutating flows
- `meal_planning_bot/handlers/settings.py` — `/settings`, `/set`
- `meal_planning_bot/formatting.py` — every reply string

## Settings used

none

## Requirements

1. The bot shall register its public command list with Telegram at startup.
2. The bot shall answer `/start` and `/help` with the command list grouped as consultation, plan, catalogue, and configuration.
3. When a user sends `/plan`, the bot shall reply with the current week's five days, each listing its five slots with dish name and effective calories, and the day's total; given the keyword `siguiente` it shall reply with next week's instead, naming the Monday that week starts on.
4. When a user sends `/today`, the bot shall reply with the current local day's five slots.
5. If `/today` is used on a Saturday or a Sunday, then the bot shall reply that the weekend is not planned.
6. If `/plan` or `/today` is used and no plan exists for the current week, then the bot shall say so and shall suggest `/regenerate`.
7. The `/swap` command shall accept a day as `lunes` through `viernes` or as 1–5, a slot as `desayuno`, `snack1`, `comida`, `snack2`, or `cena`, and an optional trailing `siguiente`.
7b. The `/plan`, `/shopping` and `/regenerate` commands shall each accept an optional `siguiente` argument, and shall address the current week when it is absent.
8. If `/swap` is given arguments it cannot parse, then the bot shall reply with the accepted forms and shall change nothing.
9. When a command that changes the plan succeeds, the bot shall reply in the chat it was called from, and shall not broadcast to the group.
10. The bot shall reply to an unknown command with the `/help` text.
11. Every reply shall be Spanish.
12. The application shall be constructed with an injectable bot and clock, so it can be assembled in a test against a fake transport and a fixed date instead of a live network connection and the real one.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/start` | both | allow-listed | Command list |
| `/help` | both | allow-listed | Command list |
| `/myid` | private | anyone | Caller's Telegram user ID |
| `/plan [siguiente]` | both | allow-listed | This week's plan, or next week's |
| `/today` | both | allow-listed | Today's five slots |
| `/shopping [siguiente]` | both | allow-listed | That week's shopping list |
| `/regenerate [siguiente]` | both | allow-listed | Re-draw that whole week |
| `/swap <day> <slot> [siguiente]` | both | allow-listed | Re-draw one slot |
| `/dishes [archivados]` | both | allow-listed | Browse active or archived dishes |
| `/dish <name>` | both | allow-listed | One dish card |
| `/foods [archivados]` | both | allow-listed | Browse active or archived foods |
| `/restore <name>` | private | allow-listed | Reactivate an archived dish or food |
| `/newdish` | private | allow-listed | Dish creation wizard |
| `/editdish` | private | allow-listed | Dish edit wizard |
| `/deletedish` | private | allow-listed | Deactivate a dish |
| `/newfood` | private | allow-listed | Food creation wizard |
| `/editfood` | private | allow-listed | Food edit wizard |
| `/deletefood` | private | allow-listed | Deactivate a food |
| `/cancel` | private | allow-listed | Abort the current wizard |
| `/settings` | both | allow-listed | Show every setting and its value |
| `/set <key> <value>` | private | allow-listed | Change one setting |

## Tests covering this

- `tests/test_handlers.py` — `/today` on a weekend, `/plan` with no plan, `/swap` argument parsing in both Spanish words and numbers, unknown commands falling back to help
- `tests/test_formatting.py` — the plan message shows per-day totals and the help text lists every registered command
- `tests/test_integration.py` — the assembled application against a fake transport and real `telegram.Update` objects, including that `build_application` accepts an injected bot and clock

## Non-goals

- An English command surface. Command names and replies are Spanish.
- Inline query mode or a persistent reply keyboard.
- Web hooks. The bot long-polls.
