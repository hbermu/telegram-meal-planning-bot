# Access Control

> Only Telegram user IDs on a fixed allow-list can interact with the bot. Catalogue management is further restricted to private chats, and scheduled posts go to exactly one configured group.

## Source files

- `meal_planning_bot/access.py` — the `allowed` and `private_only` decorators and the update filter
- `meal_planning_bot/config.py` — parses and validates `MEALBOT_ALLOWED_USER_IDS` and `MEALBOT_GROUP_CHAT_ID`
- `meal_planning_bot/__main__.py` — wraps every registered handler

## Settings used

- `MEALBOT_ALLOWED_USER_IDS` (environment) — comma-separated Telegram user IDs, required, at least one
- `MEALBOT_GROUP_CHAT_ID` (environment) — the single chat that receives scheduled posts, required

## Requirements

1. The configuration loader shall parse `MEALBOT_ALLOWED_USER_IDS` into a frozen set of integers and shall abort startup if the variable is missing, empty, or contains a non-integer.
2. The access filter shall apply to every handler except `/myid`.
3. If the effective sender's user ID is not in the allow-list, then the bot shall discard the update, log the ID at INFO, and send no reply. The ID is logged deliberately: it is how the operator notices a household member who has not been added yet, and it is the only way to tell that apart from a stranger probing. A Telegram user ID identifies a person, so these log lines are personal data and the operator must not publish them.
4. If an allow-listed user sends a command in a chat other than the configured group or a private chat with the bot, then the bot shall discard the update and send no reply.
5. When any user sends `/myid` in a private chat, the bot shall reply with that user's numeric Telegram ID.
6. The catalogue-mutating commands shall be rejected outside a private chat, with a reply telling the user to continue in private.
7. The bot shall send scheduled messages only to `MEALBOT_GROUP_CHAT_ID`.
8. The bot shall never echo the allow-list, the group chat ID, or the bot token into any message or log line.

## Commands

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/myid` | private | anyone | Replies with the caller's numeric Telegram user ID, so it can be added to the allow-list |

## Tests covering this

- `tests/test_access.py` — a non-allow-listed ID produces no reply; an allow-listed ID in an unknown chat produces no reply; `/myid` answers for anyone in private; a private-only command rejected in the group returns the redirect message

## Non-goals

- Editing the allow-list at runtime. It changes by redeploying with a new environment value.
- Roles or per-command permissions beyond the private-chat split.
- Rate limiting. The allow-list is the only gate.
