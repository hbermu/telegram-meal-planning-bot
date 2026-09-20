import sqlite3
from pathlib import Path

from meal_planning_bot.migrations import MIGRATIONS

CURRENT_VERSION = len(MIGRATIONS)


class MigrationError(Exception):
    pass


def apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > CURRENT_VERSION:
        raise MigrationError(f"database is at version {version}, code knows {CURRENT_VERSION}")
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number <= version:
            continue
        try:
            with conn:
                migration(conn)
                # PRAGMA user_version does not accept a bound parameter; `number`
                # comes from enumerate() over our own migration tuple, never user input.
                conn.execute(f"PRAGMA user_version = {number}")
        except Exception as exc:
            raise MigrationError(f"migration {number} failed") from exc


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    migrate(conn)
    return conn
