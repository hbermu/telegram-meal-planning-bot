# telegram-meal-planning-bot

A Telegram bot that runs a household's weekly meal plan: it keeps a catalogue of foods and dishes, draws a Monday-to-Friday menu at random under calorie and variety constraints, posts the plan and the aggregated shopping list to a group chat every Monday, and posts the day's meals every weekday morning.

The bot speaks Spanish. The code, the documentation, and the commit history are English.

## Features

- Monday-to-Friday plans with five slots a day: breakfast, two snacks, lunch, dinner
- A daily calorie target with a configurable tolerance
- Variety rules: no food in more than N dishes a day, and a per-meal-type cooldown before a dish can come back
- A relaxation ladder that loosens the rules in a fixed order when the catalogue is too small, and says what it loosened
- An aggregated shopping list grouped by supermarket category
- Step-by-step wizards to add dishes and foods from a phone, in a private chat
- A Telegram user allow-list; unknown users get no reply
- One SQLite file, one process, no external services

## Requirements

- Python 3.13+
- `python-telegram-bot`
- A Telegram bot token (from BotFather)
- A group chat for the scheduled posts

## Configuration

All configuration is via environment variables. Required variables cause a startup failure if not set.

### Required

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `MEALBOT_ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to interact |
| `MEALBOT_GROUP_CHAT_ID` | Chat that receives the scheduled plan and shopping list |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `MEALBOT_DB_PATH` | `/data/mealbot.db` | SQLite file. Must be local storage: SQLite's locking is unreliable over NFS and SMB. |
| `MEALBOT_TIMEZONE` | `UTC` | IANA zone for every scheduled time. Set it: the posting times mean nothing without it. |
| `MEALBOT_LOG_LEVEL` | `INFO` | Python logging level |

Everything else — the calorie target, the tolerance, the repetition limits, the cooldowns, the post times — lives in the database and is changed with `/set` from a private chat. Run `/settings` to see the current values.

Send `/myid` to the bot in a private chat to find the user ID to put in `MEALBOT_ALLOWED_USER_IDS`.

## Running

### Docker

```sh
docker run -d --name meal_planning_bot \
  -e TELEGRAM_BOT_TOKEN=... \
  -e MEALBOT_ALLOWED_USER_IDS=123456789 \
  -e MEALBOT_GROUP_CHAT_ID=-1001234567890 \
  -v meal_planning_bot-data:/data \
  ghcr.io/OWNER/telegram-meal-planning-bot:latest
```

### From source

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=... MEALBOT_ALLOWED_USER_IDS=... MEALBOT_GROUP_CHAT_ID=... \
  MEALBOT_DB_PATH=./mealbot.db .venv/bin/python -m meal_planning_bot
```

## Commands

**Consultation** — `/plan`, `/today`, `/shopping`, `/dishes`, `/dish <name>`, `/foods`

**Plan** — `/regenerate`, `/swap <day> <slot>`

**Catalogue (private chat only)** — `/newdish`, `/editdish`, `/deletedish`, `/newfood`, `/editfood`, `/deletefood`, `/cancel`

**Configuration** — `/settings`, `/set <key> <value>`

**Other** — `/start`, `/help`, `/myid`

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/mypy --strict meal_planning_bot
.venv/bin/pytest
```

Behavioural specs live under [`.agent/features/`](.agent/features/README.md) and are canonical: a change in behaviour and its spec update go in the same commit. Repository rules for contributors and AI agents are in [`AGENTS.md`](AGENTS.md).

## License

MIT. See [LICENSE](LICENSE).
