import sqlite3
from collections.abc import Iterator

import pytest

from meal_planning_bot.db import apply_pragmas, migrate


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_pragmas(connection)
    migrate(connection)
    yield connection
    connection.close()
