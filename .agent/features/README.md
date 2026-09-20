# Feature specs

Each row points to a directory under `features/` containing one or more spec files. Start with `overview.md`; read sub-spec files when your change touches that sub-functionality.

| Feature | Purpose | Sub-spec files |
|---------|---------|----------------|
| [`storage/`](storage/overview.md) | SQLite file, migrations, and the single SQL layer | `schema.md` |
| [`access-control/`](access-control/overview.md) | Telegram user allow-list, private-chat guard, and the single target group | — |
| [`catalog/`](catalog/overview.md) | Foods and dishes, and the wizards that create them | `foods.md`, `dishes.md`, `nutrition.md`, `wizards.md` |
| [`week-planner/`](week-planner/overview.md) | Random Monday-to-Friday menu under calorie and variety constraints | `constraints.md`, `relaxation.md` |
| [`shopping-list/`](shopping-list/overview.md) | Aggregating a week's ingredients into one categorised list | — |
| [`notifications/`](notifications/overview.md) | The Monday plan post and the weekday daily digest | — |
| [`command-surface/`](command-surface/overview.md) | Every command, where it works, and how it fails | `settings.md` |

## Adding a new feature

1. Copy `_template.md` to `<new-feature>/overview.md`.
2. Fill in all mandatory sections (see `../conventions.md`).
3. Add a row to this table.
4. Cross-link from any related feature whose `Non-goals` should reference the new one.
