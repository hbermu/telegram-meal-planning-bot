import sqlite3
from pathlib import Path

import pytest

from meal_planning_bot.db import CURRENT_VERSION, MigrationError, apply_pragmas, migrate
from meal_planning_bot.migrations import MIGRATIONS, SEEDED_SETTINGS


def test_fresh_database_reaches_current_version(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION


def test_reopening_applies_nothing(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION


def test_pragmas_are_set(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_future_version_aborts() -> None:
    c = sqlite3.connect(":memory:")
    apply_pragmas(c)
    c.execute(f"PRAGMA user_version = {CURRENT_VERSION + 1}")
    with pytest.raises(MigrationError):
        migrate(c)


FOOD_INSERT = "INSERT INTO foods (name, unit, category, kcal_ref) VALUES"


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (f"{FOOD_INSERT} (?, 'kg', 'pantry', 10)", ("x",)),
        (f"{FOOD_INSERT} (?, 'g', 'sweets', 10)", ("x",)),
        ("INSERT INTO dishes (name, meal_type) VALUES (?, 'brunch')", ("x",)),
        ("INSERT INTO dishes (name, meal_type, kcal_override) VALUES (?, 'lunch', 0)", ("x",)),
    ],
)
def test_check_constraints_reject(conn: sqlite3.Connection, sql: str, params: tuple[str]) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, params)


def test_case_insensitive_unique_names(conn: sqlite3.Connection) -> None:
    conn.execute(f"{FOOD_INSERT} ('Pollo', 'g', 'meat_fish', 165)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"{FOOD_INSERT} ('pollo', 'g', 'meat_fish', 165)")


def test_settings_seed_matches_documentation(conn: sqlite3.Connection) -> None:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    assert rows == SEEDED_SETTINGS


def test_kcal_ref_is_mandatory(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO foods (name, unit, category) VALUES ('x', 'g', 'pantry')")


def test_negative_kcal_ref_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"{FOOD_INSERT} ('x', 'g', 'pantry', -1)")


# --- migration 2: hand-picked plan entries ---------------------------------


def _plan_id(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO plans (week_start, generated_at) VALUES ('2026-09-14', '2026-09-13T00:00:00Z')"
    )
    row = conn.execute("SELECT id FROM plans WHERE week_start = '2026-09-14'").fetchone()
    return int(row["id"])


def _a_dish(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO foods (name, unit, category, kcal_ref) VALUES ('Arroz', 'g', 'pantry', 130)"
    )
    conn.execute("INSERT INTO dishes (name, meal_type) VALUES ('Arroz con pollo', 'lunch')")
    return int(conn.execute("SELECT id FROM dishes").fetchone()["id"])


def test_migration_two_keeps_existing_entries_as_drawn(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    apply_pragmas(old)
    with old:
        MIGRATIONS[0](old)
        old.execute("PRAGMA user_version = 1")
        plan_id = _plan_id(old)
        dish_id = _a_dish(old)
        old.execute(
            "INSERT INTO plan_entries (plan_id, day, slot, dish_id) VALUES (?, 0, 'lunch', ?)",
            (plan_id, dish_id),
        )
    old.close()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    migrate(conn)

    row = conn.execute("SELECT * FROM plan_entries").fetchone()
    assert row["dish_id"] == dish_id
    assert row["note"] is None
    assert row["override"] == 0
    conn.close()


def test_a_plan_entry_carries_either_a_dish_or_a_note(conn: sqlite3.Connection) -> None:
    plan_id = _plan_id(conn)
    dish_id = _a_dish(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO plan_entries (plan_id, day, slot, dish_id, note, override) "
            "VALUES (?, 0, 'lunch', ?, 'Fuera', 1)",
            (plan_id, dish_id),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO plan_entries (plan_id, day, slot) VALUES (?, 1, 'lunch')", (plan_id,)
        )


def test_a_note_only_exists_on_a_hand_picked_entry(conn: sqlite3.Connection) -> None:
    plan_id = _plan_id(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO plan_entries (plan_id, day, slot, note, override) "
            "VALUES (?, 0, 'lunch', 'Fuera', 0)",
            (plan_id,),
        )
