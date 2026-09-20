# Storage — schema

> The tables, their columns, and the constraints the rest of the system relies on.

## Source files

- `meal_planning_bot/migrations.py` — the `CREATE TABLE` statements and the `settings` seed rows
- `meal_planning_bot/models.py` — the dataclass mirror of each table

## Settings used

none

## Requirements

1. The `foods` table shall carry `id INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `unit TEXT NOT NULL`, `category TEXT NOT NULL`, `kcal_ref REAL NOT NULL CHECK (kcal_ref >= 0)`, `active INTEGER NOT NULL DEFAULT 1`.
2. The `foods` table shall enforce a unique index on `lower(name)` so that a food cannot be created twice under different capitalisation.
3. The `foods.unit` column shall accept only `g`, `ml`, or `unit`, enforced by a `CHECK` constraint.
4. The `foods.category` column shall accept only `produce`, `meat_fish`, `dairy_eggs`, `bakery`, `pantry`, `frozen`, `drinks`, or `other`, enforced by a `CHECK` constraint.
5. The `dishes` table shall carry `id INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `meal_type TEXT NOT NULL`, `kcal_override INTEGER`, `steps TEXT`, `active INTEGER NOT NULL DEFAULT 1`.
6. The `dishes` table shall enforce a unique index on `lower(name)`.
7. The `dishes.meal_type` column shall accept only `breakfast`, `snack`, `lunch`, or `dinner`, enforced by a `CHECK` constraint.
8. The `dishes.kcal_override` column shall be nullable and shall accept only values greater than zero when present, enforced by a `CHECK` constraint. A dish without an override takes its calories from its ingredients, as defined in `../catalog/nutrition.md`.
9. The `dish_ingredients` table shall carry `dish_id INTEGER NOT NULL REFERENCES dishes(id)`, `food_id INTEGER NOT NULL REFERENCES foods(id)`, `quantity REAL NOT NULL CHECK (quantity > 0)`, with `PRIMARY KEY (dish_id, food_id)` so a food appears at most once per dish.
10. The `plans` table shall carry `id INTEGER PRIMARY KEY`, `week_start TEXT NOT NULL UNIQUE`, `generated_at TEXT NOT NULL`, `relaxation INTEGER NOT NULL DEFAULT 0`.
11. The `plan_entries` table shall carry `plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE`, `day INTEGER NOT NULL CHECK (day BETWEEN 0 AND 4)`, `slot TEXT NOT NULL`, `dish_id INTEGER NOT NULL REFERENCES dishes(id)`, with `PRIMARY KEY (plan_id, day, slot)`.
12. The `plan_entries.slot` column shall accept only `breakfast`, `snack1`, `lunch`, `snack2`, or `dinner`, enforced by a `CHECK` constraint.
13. The `settings` table shall carry `key TEXT PRIMARY KEY` and `value TEXT NOT NULL`, and shall be seeded by migration 1 with every key listed in `../command-surface/settings.md`.
14. When a dish is deactivated, the schema shall keep its `dish_ingredients` rows and every `plan_entries` row that references it.

## Tests covering this

- `tests/test_migrations.py` — every `CHECK` constraint rejects an out-of-range value; the `lower(name)` unique indexes reject a case-variant duplicate; the `settings` seed contains exactly the documented keys
- `tests/test_repo.py` — a plan's entries disappear when the plan is deleted, and a deactivated dish keeps its ingredient rows

## Non-goals

- Per-user or per-profile scoping. There is one household and one plan per week.
- Snapshotting a dish's calories onto a plan entry. A plan stores dish identifiers; calories are resolved when the plan is read.
- Historical shopping lists. A list is derived from a plan on demand, never stored.
