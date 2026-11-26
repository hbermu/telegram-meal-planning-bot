import sqlite3
from collections.abc import Callable

# Keys and defaults mirror .agent/features/command-surface/settings.md exactly.
SEEDED_SETTINGS: dict[str, str] = {
    "daily_kcal_target": "2000",
    "kcal_tolerance_pct": "10",
    "max_food_repeats_per_day": "2",
    "cooldown_days_breakfast": "1",
    "cooldown_days_snack": "1",
    "cooldown_days_lunch": "14",
    "cooldown_days_dinner": "1",
    "weekly_post_weekday": "4",
    "weekly_post_time": "18:00",
    "daily_post_time": "08:00",
}

_SCHEMA = """
CREATE TABLE foods (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL CHECK (unit IN ('g', 'ml', 'unit')),
    category TEXT NOT NULL CHECK (
        category IN (
            'produce', 'meat_fish', 'dairy_eggs', 'bakery',
            'pantry', 'frozen', 'drinks', 'other'
        )
    ),
    kcal_ref REAL NOT NULL CHECK (kcal_ref >= 0),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX foods_name_lower ON foods (lower(name));

CREATE TABLE dishes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'snack', 'lunch', 'dinner')),
    kcal_override INTEGER CHECK (kcal_override IS NULL OR kcal_override > 0),
    steps TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX dishes_name_lower ON dishes (lower(name));

CREATE TABLE dish_ingredients (
    dish_id INTEGER NOT NULL REFERENCES dishes(id),
    food_id INTEGER NOT NULL REFERENCES foods(id),
    quantity REAL NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (dish_id, food_id)
);

CREATE TABLE plans (
    id INTEGER PRIMARY KEY,
    week_start TEXT NOT NULL UNIQUE,
    generated_at TEXT NOT NULL,
    relaxation INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE plan_entries (
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day INTEGER NOT NULL CHECK (day BETWEEN 0 AND 4),
    slot TEXT NOT NULL CHECK (slot IN ('breakfast', 'snack1', 'lunch', 'snack2', 'dinner')),
    dish_id INTEGER NOT NULL REFERENCES dishes(id),
    PRIMARY KEY (plan_id, day, slot)
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        list(SEEDED_SETTINGS.items()),
    )


_PLAN_ENTRY_OVERRIDES: tuple[str, ...] = (
    """
CREATE TABLE plan_entries_new (
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day INTEGER NOT NULL CHECK (day BETWEEN 0 AND 4),
    slot TEXT NOT NULL CHECK (slot IN ('breakfast', 'snack1', 'lunch', 'snack2', 'dinner')),
    dish_id INTEGER REFERENCES dishes(id),
    note TEXT,
    override INTEGER NOT NULL DEFAULT 0 CHECK (override IN (0, 1)),
    CHECK ((dish_id IS NOT NULL) <> (note IS NOT NULL)),
    CHECK (note IS NULL OR override = 1),
    PRIMARY KEY (plan_id, day, slot)
)
""",
    "INSERT INTO plan_entries_new (plan_id, day, slot, dish_id) "
    "SELECT plan_id, day, slot, dish_id FROM plan_entries",
    "DROP TABLE plan_entries",
    "ALTER TABLE plan_entries_new RENAME TO plan_entries",
)


def _add_plan_entry_overrides(conn: sqlite3.Connection) -> None:
    # SQLite cannot relax a NOT NULL, so the table is rebuilt. One statement at
    # a time rather than a script: executescript commits first, which would
    # take this rebuild of someone's stored plans out of the migration's
    # transaction and leave the table half replaced if a later step failed.
    # Nothing references plan_entries, which is what makes dropping it safe.
    for statement in _PLAN_ENTRY_OVERRIDES:
        conn.execute(statement)


_PLAN_ENTRY_NOTE_KCAL: tuple[str, ...] = (
    """
CREATE TABLE plan_entries_new (
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day INTEGER NOT NULL CHECK (day BETWEEN 0 AND 4),
    slot TEXT NOT NULL CHECK (slot IN ('breakfast', 'snack1', 'lunch', 'snack2', 'dinner')),
    dish_id INTEGER REFERENCES dishes(id),
    note TEXT,
    kcal INTEGER CHECK (kcal IS NULL OR kcal > 0),
    override INTEGER NOT NULL DEFAULT 0 CHECK (override IN (0, 1)),
    CHECK ((dish_id IS NOT NULL) <> (note IS NOT NULL)),
    CHECK (note IS NULL OR override = 1),
    CHECK (kcal IS NULL OR note IS NOT NULL),
    PRIMARY KEY (plan_id, day, slot)
)
""",
    "INSERT INTO plan_entries_new (plan_id, day, slot, dish_id, note, override) "
    "SELECT plan_id, day, slot, dish_id, note, override FROM plan_entries",
    "DROP TABLE plan_entries",
    "ALTER TABLE plan_entries_new RENAME TO plan_entries",
)


def _add_plan_entry_note_kcal(conn: sqlite3.Connection) -> None:
    # Rebuilt rather than altered for the same reason as migration 2: the
    # invariant that only a note may carry calories is a table-level CHECK,
    # which ALTER TABLE cannot add. Existing notes keep no calories, which is
    # what they were worth before anybody could say otherwise.
    for statement in _PLAN_ENTRY_NOTE_KCAL:
        conn.execute(statement)


MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _create_schema,
    _add_plan_entry_overrides,
    _add_plan_entry_note_kcal,
)
