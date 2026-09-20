# <Feature Name>

> One-paragraph purpose statement. What this feature gives the user.

## Source files

- `meal_planning_bot/<path>.py` — what it contributes to this feature
- `meal_planning_bot/<path>.py` — ...

## Settings used

- `SETTING_KEY` (environment) — short description
- `setting_key` (settings table) — short description

Write `none` if the feature reads neither.

## Requirements

EARS patterns:
- Ubiquitous: `The <subsystem> shall <response>.`
- Event-driven: `When <trigger>, the <subsystem> shall <response>.`
- State-driven: `While <state>, the <subsystem> shall <response>.`
- Conditional: `If <condition>, then the <subsystem> shall <response>.`

1. The <subsystem> shall <response>.
2. When <event>, the <subsystem> shall <response>.
3. While <state>, the <subsystem> shall <response>.

## Commands

(Include this section only if the feature adds Telegram commands. Otherwise delete it.)

| Command | Where | Who | Effect |
|---------|-------|-----|--------|
| `/name <arg>` | group / private / both | allow-listed | What it does |

## Tests covering this

- `tests/test_<name>.py` — what it asserts
- `tests/test_<name>.py` — ...

## Non-goals

- <Things this feature explicitly does not do — guards against future scope creep>
- <One non-goal per bullet>
