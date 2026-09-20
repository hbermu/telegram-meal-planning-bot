import sqlite3

import pytest

from meal_planning_bot.db import CURRENT_VERSION, MigrationError, apply_pragmas, migrate
from meal_planning_bot.migrations import SEEDED_SETTINGS


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
