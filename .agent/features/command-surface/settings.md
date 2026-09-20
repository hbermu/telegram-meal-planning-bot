# Command Surface — settings

> The tunable values live in the database, not the environment, so they can be changed from a phone without a redeploy. Everything that is a secret or an identity stays in the environment.

## Source files

- `meal_planning_bot/handlers/settings.py` — `/settings` and `/set`
- `meal_planning_bot/repo.py` — `get_setting`, `set_setting`, `all_settings`
- `meal_planning_bot/migrations.py` — the seed values

## Settings used

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `daily_kcal_target` | integer, 800–6000 | `2000` | Target calories per day |
| `kcal_tolerance_pct` | integer, 0–50 | `10` | Allowed deviation from the target |
| `max_food_repeats_per_day` | integer, 1–5 | `2` | How many dishes in a day may share one food |
| `cooldown_days_breakfast` | integer, 1–60 | `1` | Minimum gap before a breakfast repeats |
| `cooldown_days_snack` | integer, 1–60 | `1` | Minimum gap before a snack repeats |
| `cooldown_days_lunch` | integer, 1–60 | `14` | Minimum gap before a lunch repeats |
| `cooldown_days_dinner` | integer, 1–60 | `1` | Minimum gap before a dinner repeats |
| `weekly_post_weekday` | integer, 0–6 | `4` | Weekday of the planning post, 0 Monday to 6 Sunday |
| `weekly_post_time` | `HH:MM` | `18:00` | Local time of the planning post |
| `daily_post_time` | `HH:MM` | `08:00` | Local time of the weekday post |

## Requirements

1. The settings table shall be seeded with exactly the keys in the table above and no others.
2. When a user sends `/settings`, the bot shall reply with every key, its current value, and its default.
3. When a user sends `/set <key> <value>`, the bot shall validate the value against that key's type and range and shall store it only if it passes.
4. If `/set` is given an unknown key, then the bot shall reply with the list of valid keys and shall change nothing.
5. If `/set` is given a value outside the key's range or of the wrong type, then the bot shall reply with the accepted range and shall change nothing.
6. The `/set` command shall be rejected outside a private chat.
7. When a setting is changed, the bot shall confirm with the old and the new value.
8. A changed planner setting shall take effect on the next plan generation without a restart.
9. A changed post weekday or time shall re-register the affected scheduled job without a restart, as required by `../notifications/overview.md`.
10. The bot token, the allow-list, the group chat ID, the database path, and the timezone shall never be exposed as settings keys.

## Tests covering this

- `tests/test_settings.py` — every key validates its range; an unknown key changes nothing; a bad value changes nothing; the seed matches the documented key list exactly; the confirmation shows both values

## Non-goals

- Per-user settings. There is one household configuration.
- Changing the environment-provided values at runtime.
- A settings UI beyond `/settings` and `/set`.
