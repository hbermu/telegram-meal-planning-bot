# Storage

> A single SQLite file holds the food and dish catalogue, every generated plan, and the runtime settings. All SQL in the project lives in `repo.py`; the schema is created and evolved by numbered migrations keyed off `PRAGMA user_version`.

## Source files

- `meal_planning_bot/db.py` — connection factory, PRAGMAs, migration dispatch on open
- `meal_planning_bot/migrations.py` — the ordered list of migration functions and the seed data for `settings`
- `meal_planning_bot/models.py` — the dataclasses every other module passes around
- `meal_planning_bot/repo.py` — every SQL statement in the project

## Settings used

- `MEALBOT_DB_PATH` (environment) — absolute path to the SQLite file, default `/data/mealbot.db`

## Requirements

1. The database module shall open the file at `MEALBOT_DB_PATH`, creating it and its parent directory if absent.
2. The database module shall set `journal_mode = WAL`, `foreign_keys = ON`, and `busy_timeout = 5000` on every connection.
3. When a connection is opened, the database module shall read `PRAGMA user_version` and apply, in ascending order, every migration whose number is greater than that value, each inside its own transaction, setting `user_version` to the migration's number as the last statement of that transaction.
4. If a migration raises, then the database module shall roll that migration's transaction back, leave `user_version` at the last successful migration, and abort startup with the failing migration's number in the log.
5. The database module shall never downgrade: a `user_version` higher than the highest known migration aborts startup.
6. The repository shall be the only module that executes SQL, alongside `db.py` and `migrations.py`. Other modules may import `sqlite3.Connection` for a type annotation but shall not open a connection or call `execute`, `executemany` or `executescript`.
7. The repository shall return dataclasses from `models.py`, never raw rows or tuples.
8. The repository shall never issue `DELETE` against `foods` or `dishes`; removal is setting `active = 0`, and restoration is setting it back to `1`.
9. The repository shall store every date as an ISO `YYYY-MM-DD` string and every timestamp as an ISO 8601 UTC string.

## Tests covering this

- `tests/test_migrations.py` — a fresh file reaches the current `user_version`; re-opening applies nothing; a `user_version` above the highest known migration aborts; a raising migration leaves the previous version intact
- `tests/test_repo.py` — round-trips for every dataclass, soft deletion, the uniqueness constraints, that a dish keeps its ingredients when deactivated, that a saved plan reads back with its slots in `SLOT_ORDER`, and that no module outside the SQL layer executes SQL
- `tests/test_wizards.py` — a dish rejected mid-write leaves neither the dish nor its inline-created food

## Non-goals

- Concurrent writers. One process owns the file; there is no connection pool and no locking strategy beyond `busy_timeout`.
- Backups. Whatever deploys this owns that, not this code.
- An ORM. Hand-written SQL in one module is the whole data layer.
- Schema downgrades or reversible migrations.
