# Meal-planning Telegram bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a Telegram bot that keeps a food and dish catalogue, draws a constrained Monday-to-Friday menu each week, and posts the plan, the shopping list, and a daily digest to a group chat.

**Architecture:** One long-running Python process. A pure solver (`planner.py`) and a pure aggregator (`shopping.py`) hold all the logic and are unit-tested against synthetic catalogues with no I/O. Everything stateful goes through `repo.py`, the only module that executes SQL, against a SQLite file. `python-telegram-bot` supplies the command handlers, the `ConversationHandler` wizards, and the `JobQueue` schedule. Every Spanish string lives in `formatting.py`.

**Tech Stack:** Python 3.13, `python-telegram-bot`, SQLite (stdlib `sqlite3`), pytest, mypy `--strict`, ruff, Docker, GitHub Actions → GHCR (public package).

**User Verification:** NO — the spec requires no human-in-the-loop confirmation step. Each task is verified by its own test command.

**Canonical spec:** `.agent/features/**`. Every task below names the spec files it implements. A task is not done until its code satisfies every EARS requirement in those files, and any deviation is fixed in the spec in the same commit.

**Conventions for every task:**
- TDD: write the failing test, watch it fail, implement, watch it pass, commit.
- Before each commit: `.venv/bin/ruff check . && .venv/bin/mypy --strict meal_planning_bot && .venv/bin/pytest`
- Commit subjects: `<type>(<scope>): <subject>`, scopes `planner`, `catalog`, `shopping`, `notifications`, `access`, `storage`, `commands`, `deps`, `ci`, `docs`, `repo`.
- Tests never open a socket and never touch Telegram's servers.

---

### Task 1: Project scaffolding

**Goal:** A working virtualenv, lint/type/test tooling, an importable empty package, and a CI job that runs all three.

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `meal_planning_bot/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`, `.github/workflows/ci.yml`

**Acceptance Criteria:**
- [ ] `.venv/bin/pytest` collects and passes one smoke test
- [ ] `.venv/bin/mypy --strict meal_planning_bot` passes on the empty package
- [ ] `.venv/bin/ruff check .` passes
- [ ] The CI workflow runs ruff, mypy and pytest on push and pull request

**Verify:** `.venv/bin/ruff check . && .venv/bin/mypy --strict meal_planning_bot && .venv/bin/pytest -q` → all pass, 1 test

**Steps:**

- [ ] **Step 1: Create the virtualenv and dependency files**

`requirements.txt`:
```
python-telegram-bot[job-queue]==21.9
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
mypy==1.14.1
ruff==0.9.2
```

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

- [ ] **Step 2: Configure the tooling**

`pyproject.toml`:
```toml
[project]
name = "meal_planning_bot"
version = "0.1.0"
requires-python = ">=3.13"

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_unreachable = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: Write the smoke test and watch it fail**

`tests/test_smoke.py`:
```python
def test_package_imports() -> None:
    import meal_planning_bot

    assert meal_planning_bot.__name__ == "meal_planning_bot"
```

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'meal_planning_bot'`

- [ ] **Step 4: Create the package and watch it pass**

```bash
mkdir -p meal_planning_bot tests
touch meal_planning_bot/__init__.py tests/__init__.py
```

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Add the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: mypy --strict meal_planning_bot
      - run: pytest
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt requirements-dev.txt meal_planning_bot tests .github/workflows/ci.yml
git commit -m "chore(repo): scaffold package, tooling and CI"
```

---

### Task 2: Configuration from the environment

**Goal:** A frozen `Config` dataclass built from environment variables that aborts startup with a clear message on anything missing or malformed.

**Spec:** `.agent/features/access-control/overview.md` (1), `.agent/features/storage/overview.md` (1), `.agent/features/notifications/overview.md` (1)

**Files:**
- Create: `meal_planning_bot/config.py`, `tests/test_config.py`

**Acceptance Criteria:**
- [ ] `TELEGRAM_BOT_TOKEN`, `MEALBOT_ALLOWED_USER_IDS`, `MEALBOT_GROUP_CHAT_ID` are required; a missing one raises `ConfigError` naming the variable
- [ ] `MEALBOT_ALLOWED_USER_IDS` parses to a `frozenset[int]`; empty or non-integer raises
- [ ] `MEALBOT_DB_PATH` defaults to `/data/mealbot.db`, `MEALBOT_TIMEZONE` to `UTC`, `MEALBOT_LOG_LEVEL` to `INFO`
- [ ] An unknown timezone raises `ConfigError`
- [ ] `repr(Config)` never contains the token

**Verify:** `.venv/bin/pytest tests/test_config.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest

from meal_planning_bot.config import ConfigError, load_config

BASE = {
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "MEALBOT_ALLOWED_USER_IDS": "1, 2,3",
    "MEALBOT_GROUP_CHAT_ID": "-1001",
}


def test_parses_defaults() -> None:
    cfg = load_config(BASE)
    assert cfg.allowed_user_ids == frozenset({1, 2, 3})
    assert cfg.group_chat_id == -1001
    assert cfg.db_path.as_posix() == "/data/mealbot.db"
    assert cfg.timezone == "UTC"


@pytest.mark.parametrize("missing", list(BASE))
def test_missing_required_names_the_variable(missing: str) -> None:
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


@pytest.mark.parametrize("bad", ["", " ", "1,x", "1,,2"])
def test_bad_allow_list_rejected(bad: str) -> None:
    with pytest.raises(ConfigError, match="MEALBOT_ALLOWED_USER_IDS"):
        load_config(BASE | {"MEALBOT_ALLOWED_USER_IDS": bad})


def test_unknown_timezone_rejected() -> None:
    with pytest.raises(ConfigError, match="MEALBOT_TIMEZONE"):
        load_config(BASE | {"MEALBOT_TIMEZONE": "Mars/Olympus"})


def test_token_not_in_repr() -> None:
    assert "123:abc" not in repr(load_config(BASE))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'meal_planning_bot.config'`

- [ ] **Step 3: Implement**

`meal_planning_bot/config.py`:
```python
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    allowed_user_ids: frozenset[int]
    group_chat_id: int
    db_path: Path
    timezone: str
    log_level: str


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _parse_allow_list(raw: str) -> frozenset[int]:
    parts = [p.strip() for p in raw.split(",")]
    if any(not p for p in parts):
        raise ConfigError("MEALBOT_ALLOWED_USER_IDS must be a comma-separated list of user IDs")
    try:
        return frozenset(int(p) for p in parts)
    except ValueError as exc:
        raise ConfigError("MEALBOT_ALLOWED_USER_IDS must contain integers only") from exc


def load_config(env: Mapping[str, str]) -> Config:
    token = _required(env, "TELEGRAM_BOT_TOKEN")
    allowed = _parse_allow_list(_required(env, "MEALBOT_ALLOWED_USER_IDS"))
    try:
        group_chat_id = int(_required(env, "MEALBOT_GROUP_CHAT_ID"))
    except ValueError as exc:
        raise ConfigError("MEALBOT_GROUP_CHAT_ID must be an integer") from exc

    timezone = env.get("MEALBOT_TIMEZONE", "UTC").strip() or "UTC"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"MEALBOT_TIMEZONE is not a known zone: {timezone}") from exc

    return Config(
        token=token,
        allowed_user_ids=allowed,
        group_chat_id=group_chat_id,
        db_path=Path(env.get("MEALBOT_DB_PATH", "/data/mealbot.db")),
        timezone=timezone,
        log_level=env.get("MEALBOT_LOG_LEVEL", "INFO").upper(),
    )
```

`env` is a `Mapping`, not a `dict`: `os.environ` is an `os._Environ[str]`, and `mypy --strict` rejects passing it where a `dict[str, str]` is declared. Task 19 calls this with `os.environ`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add meal_planning_bot/config.py tests/test_config.py
git commit -m "feat(access): load and validate configuration from the environment"
```

---

### Task 3: Models, database and migrations

**Goal:** The dataclasses every module passes around, a connection factory with the required PRAGMAs, and migration 1 creating the whole schema with its CHECK constraints and settings seed.

**Spec:** `.agent/features/storage/overview.md`, `.agent/features/storage/schema.md`, `.agent/features/command-surface/settings.md` (1)

**Files:**
- Create: `meal_planning_bot/models.py`, `meal_planning_bot/db.py`, `meal_planning_bot/migrations.py`, `tests/test_migrations.py`, `tests/conftest.py`

**Acceptance Criteria:**
- [ ] A fresh file reaches `user_version = 1`; re-opening applies nothing
- [ ] `journal_mode = WAL`, `foreign_keys = ON`, `busy_timeout = 5000` on every connection
- [ ] A `user_version` above the highest known migration aborts with `MigrationError`
- [ ] A raising migration rolls back and leaves `user_version` at the previous value
- [ ] Every CHECK constraint in `schema.md` rejects an out-of-range value
- [ ] Both `lower(name)` unique indexes reject a case-variant duplicate
- [ ] The `settings` seed contains exactly the ten keys in `settings.md`, with the documented defaults

**Verify:** `.venv/bin/pytest tests/test_migrations.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write `tests/conftest.py` with the in-memory fixture**

```python
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
```

- [ ] **Step 2: Write the failing migration tests**

`tests/test_migrations.py` must cover, one test each:
```python
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


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ("INSERT INTO foods (name, unit, category, kcal_ref) VALUES (?, 'kg', 'pantry', 10)", ("x",)),
        ("INSERT INTO foods (name, unit, category, kcal_ref) VALUES (?, 'g', 'sweets', 10)", ("x",)),
        ("INSERT INTO foods (name, unit, category) VALUES (?, 'g', 'pantry')", ("x",)),
        ("INSERT INTO dishes (name, meal_type) VALUES (?, 'brunch')", ("x",)),
        ("INSERT INTO dishes (name, meal_type, kcal_override) VALUES (?, 'lunch', 0)", ("x",)),
    ],
)
def test_check_constraints_reject(conn: sqlite3.Connection, sql: str, params: tuple[str]) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, params)


def test_case_insensitive_unique_names(conn: sqlite3.Connection) -> None:
    insert = "INSERT INTO foods (name, unit, category, kcal_ref) VALUES (?, 'g', 'meat_fish', 165)"
    conn.execute(insert, ("Pollo",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("pollo",))

Note the third `foods` case: omitting `kcal_ref` must fail. `kcal_ref` is `NOT NULL` with no
default on purpose — a food silently defaulting to zero calories would make every dish using it
quietly wrong, which is worse than a failed insert.


def test_settings_seed_matches_documentation(conn: sqlite3.Connection) -> None:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    assert rows == SEEDED_SETTINGS
```

Run: `.venv/bin/pytest tests/test_migrations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mealbot.db'`

- [ ] **Step 3: Implement `meal_planning_bot/models.py`**

```python
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Unit(StrEnum):
    G = "g"
    ML = "ml"
    UNIT = "unit"


# A food's kcal_ref is the calories of this much of it.
REFERENCE_QUANTITY: dict[Unit, float] = {Unit.G: 100.0, Unit.ML: 100.0, Unit.UNIT: 1.0}


class Category(StrEnum):
    PRODUCE = "produce"
    MEAT_FISH = "meat_fish"
    DAIRY_EGGS = "dairy_eggs"
    BAKERY = "bakery"
    FROZEN = "frozen"
    PANTRY = "pantry"
    DRINKS = "drinks"
    OTHER = "other"


CATEGORY_ORDER: tuple[Category, ...] = (
    Category.PRODUCE,
    Category.MEAT_FISH,
    Category.DAIRY_EGGS,
    Category.BAKERY,
    Category.FROZEN,
    Category.PANTRY,
    Category.DRINKS,
    Category.OTHER,
)


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    SNACK = "snack"
    LUNCH = "lunch"
    DINNER = "dinner"


class Slot(StrEnum):
    BREAKFAST = "breakfast"
    SNACK1 = "snack1"
    LUNCH = "lunch"
    SNACK2 = "snack2"
    DINNER = "dinner"


SLOT_ORDER: tuple[Slot, ...] = (
    Slot.BREAKFAST,
    Slot.SNACK1,
    Slot.LUNCH,
    Slot.SNACK2,
    Slot.DINNER,
)

SLOT_MEAL_TYPE: dict[Slot, MealType] = {
    Slot.BREAKFAST: MealType.BREAKFAST,
    Slot.SNACK1: MealType.SNACK,
    Slot.LUNCH: MealType.LUNCH,
    Slot.SNACK2: MealType.SNACK,
    Slot.DINNER: MealType.DINNER,
}


@dataclass(frozen=True)
class Food:
    id: int
    name: str
    unit: Unit
    category: Category
    kcal_ref: float
    active: bool = True


@dataclass(frozen=True)
class DishIngredient:
    food_id: int
    quantity: float


@dataclass(frozen=True)
class Dish:
    id: int
    name: str
    meal_type: MealType
    kcal: int                  # effective: the override when set, else computed
    ingredients: tuple[DishIngredient, ...]
    kcal_override: int | None = None
    steps: str | None = None
    active: bool = True


@dataclass(frozen=True)
class PlanEntry:
    day: int
    slot: Slot
    dish_id: int


@dataclass(frozen=True)
class Plan:
    week_start: date
    entries: tuple[PlanEntry, ...]
    relaxation: int = 0


@dataclass(frozen=True)
class ServedRecord:
    dish_id: int
    served_on: date


# `kcal` is resolved by repo.py when a Dish is loaded, so planner.py never needs the
# food table and stays a pure function of its arguments. `kcal_override` is kept only
# so formatting can say whether the figure was computed or typed.


@dataclass(frozen=True)
class PlannerSettings:
    daily_kcal_target: int
    kcal_tolerance_pct: int
    max_food_repeats_per_day: int
    cooldown_days: Mapping[MealType, int]
```

`PlannerSettings` lives here, not in `planner.py`, so that `repo.planner_settings()` (Task 6) can build one without importing the solver.

- [ ] **Step 4: Implement `meal_planning_bot/migrations.py`**

Define `SEEDED_SETTINGS: dict[str, str]` with exactly the nine keys and defaults from `.agent/features/command-surface/settings.md`, then `MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...]` whose first entry issues the `CREATE TABLE` statements from `.agent/features/storage/schema.md` verbatim — every CHECK, both `CREATE UNIQUE INDEX ... ON foods (lower(name))` / `dishes (lower(name))`, and the seed inserts.

```python
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
```

- [ ] **Step 5: Implement `meal_planning_bot/db.py`**

```python
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
```

Note: `PRAGMA user_version` does not accept a bound parameter, hence the f-string — `number` is an integer from `enumerate`, never user input.

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/pytest tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add meal_planning_bot/models.py meal_planning_bot/db.py meal_planning_bot/migrations.py tests/conftest.py tests/test_migrations.py
git commit -m "feat(storage): add models, connection factory and the initial migration"
```

---

### Task 4: Calories and weeks — the pure helpers

**Goal:** Two small pure modules — calorie resolution from ingredients, and week arithmetic — plus the curated seed file of common ingredients so the household does not have to look calorie densities up.

**Spec:** `.agent/features/catalog/nutrition.md`, `.agent/features/notifications/overview.md` (3, 8, 9, 14)

**Files:**
- Create: `meal_planning_bot/nutrition.py`, `meal_planning_bot/weeks.py`, `meal_planning_bot/data/kcal_seed.json`, `tests/test_nutrition.py`, `tests/test_weeks.py`, `scripts/build_kcal_seed.py`

**Acceptance Criteria:**
- [ ] `computed_kcal` sums `quantity / REFERENCE_QUANTITY[unit] * kcal_ref` and rounds to a whole calorie
- [ ] A `unit`-based food (an egg at 78 kcal each, quantity 2) contributes 156, not 1.56
- [ ] `effective_kcal` returns the override when set and the computed value when not
- [ ] The seed lookup matches on the lower-cased name exactly and returns `None` otherwise — no fuzzy matching
- [ ] Every seed entry has a valid `Unit`, a valid `Category`, and a `kcal_ref` between 0 and 900
- [ ] Ten hand-checked anchors match the seed within ±5 kcal (`aceite de oliva` 884, `arroz` 360, `pollo` 165, `huevo` 78 per unit, and six more chosen when the seed is built)
- [ ] `current_week_start`, `next_week_start` and `resolve_week` handle a Monday, a Friday and a Sunday correctly
- [ ] `resolve_week` maps the argument `siguiente` to next Monday and its absence to the current week
- [ ] Neither module imports `sqlite3`, `telegram`, or reads the clock — the date is always a parameter

**Verify:** `.venv/bin/pytest tests/test_nutrition.py tests/test_weeks.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing calorie tests**

```python
from meal_planning_bot.models import Category, DishIngredient, Food, Unit
from meal_planning_bot.nutrition import computed_kcal, effective_kcal, seed_lookup

RICE = Food(id=1, name="Arroz", unit=Unit.G, category=Category.PANTRY, kcal_ref=360.0)
EGG = Food(id=2, name="Huevo", unit=Unit.UNIT, category=Category.DAIRY_EGGS, kcal_ref=78.0)
MILK = Food(id=3, name="Leche", unit=Unit.ML, category=Category.DAIRY_EGGS, kcal_ref=64.0)


def test_grams_use_a_reference_of_one_hundred() -> None:
    assert computed_kcal([DishIngredient(1, 80.0)], {1: RICE}) == 288


def test_units_use_a_reference_of_one() -> None:
    assert computed_kcal([DishIngredient(2, 2.0)], {2: EGG}) == 156


def test_millilitres_use_a_reference_of_one_hundred() -> None:
    assert computed_kcal([DishIngredient(3, 250.0)], {3: MILK}) == 160


def test_override_wins() -> None:
    assert effective_kcal([DishIngredient(1, 80.0)], {1: RICE}, override=500) == 500
    assert effective_kcal([DishIngredient(1, 80.0)], {1: RICE}, override=None) == 288


def test_seed_lookup_is_exact() -> None:
    assert seed_lookup("Aceite de oliva") is not None
    assert seed_lookup("aceite de olivaa") is None
```

Run: `.venv/bin/pytest tests/test_nutrition.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'meal_planning_bot.nutrition'`

- [ ] **Step 2: Implement `meal_planning_bot/nutrition.py`**

```python
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from meal_planning_bot.models import REFERENCE_QUANTITY, Category, DishIngredient, Food, Unit


@dataclass(frozen=True)
class SeedEntry:
    unit: Unit
    category: Category
    kcal_ref: float


@cache
def _seed() -> dict[str, SeedEntry]:
    raw = json.loads(files("meal_planning_bot.data").joinpath("kcal_seed.json").read_text("utf-8"))
    return {
        name.lower(): SeedEntry(Unit(e["unit"]), Category(e["category"]), float(e["kcal_ref"]))
        for name, e in raw.items()
    }


def seed_lookup(name: str) -> SeedEntry | None:
    return _seed().get(name.strip().lower())


def computed_kcal(ingredients: Sequence[DishIngredient], foods: Mapping[int, Food]) -> int:
    total = 0.0
    for ingredient in ingredients:
        food = foods[ingredient.food_id]
        total += ingredient.quantity / REFERENCE_QUANTITY[food.unit] * food.kcal_ref
    return round(total)


def effective_kcal(ingredients, foods, override: int | None) -> int:
    return override if override is not None else computed_kcal(ingredients, foods)
```

- [ ] **Step 3: Build the seed file**

`scripts/build_kcal_seed.py` reads a USDA FoodData Central bulk download (the *Foundation Foods* and *SR Legacy* sets, which are public domain) plus a hand-written Spanish-name mapping, and writes `meal_planning_bot/data/kcal_seed.json`:

```json
{
  "aceite de oliva": {"unit": "g", "category": "pantry", "kcal_ref": 884},
  "arroz": {"unit": "g", "category": "pantry", "kcal_ref": 360},
  "huevo": {"unit": "unit", "category": "dairy_eggs", "kcal_ref": 78}
}
```

Target roughly 200 entries covering what the household actually buys. The script is committed so the file can be regenerated and audited; it is **not** run by the bot. Note in its module docstring that the values are per the reference quantity defined in `models.REFERENCE_QUANTITY`, and that they are approximations of generic ingredients, not of specific brands.

- [ ] **Step 4: Write the seed validation test**

```python
ANCHORS = {"aceite de oliva": 884, "arroz": 360, "pollo": 165, "huevo": 78, ...}


def test_every_seed_entry_is_well_formed() -> None:
    for name, entry in _seed().items():
        assert name == name.lower()
        assert isinstance(entry.unit, Unit)
        assert isinstance(entry.category, Category)
        assert 0 <= entry.kcal_ref <= 900, f"{name} has an implausible kcal_ref"


@pytest.mark.parametrize(("name", "expected"), ANCHORS.items())
def test_anchor_values(name: str, expected: int) -> None:
    entry = seed_lookup(name)
    assert entry is not None
    assert abs(entry.kcal_ref - expected) <= 5
```

The upper bound of 900 exists because pure fat is about 884 kcal per 100 g; anything above that is a data-entry error, not a food.

- [ ] **Step 5: Implement `meal_planning_bot/weeks.py`**

```python
from datetime import date, timedelta

NEXT_KEYWORD = "siguiente"


def current_week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def next_week_start(today: date) -> date:
    return current_week_start(today) + timedelta(days=7)


def resolve_week(args: Sequence[str], today: date) -> tuple[date, bool]:
    """Returns (week_start, is_next). Raises ArgumentError on an unknown argument."""
```

- [ ] **Step 6: Write the week tests**

Cover a Monday, a Friday and a Sunday for both functions, and `resolve_week` with `[]`, `["siguiente"]` and `["proxima"]` (which raises).

- [ ] **Step 7: Run to verify pass**

Run: `.venv/bin/pytest tests/test_nutrition.py tests/test_weeks.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add meal_planning_bot/nutrition.py meal_planning_bot/weeks.py meal_planning_bot/data scripts/build_kcal_seed.py \
        tests/test_nutrition.py tests/test_weeks.py
git commit -m "feat(catalog): compute dish calories from ingredients and resolve weeks"
```

---

### Task 5: Repository — foods and dishes

**Goal:** Every catalogue read and write, with case-insensitive names, soft deletion, and the referential guards the spec requires.

**Spec:** `.agent/features/catalog/foods.md`, `.agent/features/catalog/dishes.md`, `.agent/features/storage/overview.md` (6–9)

**Files:**
- Create: `meal_planning_bot/repo.py`, `tests/test_repo.py`

**Acceptance Criteria:**
- [ ] `create_food` stores `kcal_ref`, rejects a case-variant duplicate, and preserves the typed capitalisation
- [ ] `deactivate_food` is refused with the referencing dish names while any dish uses it
- [ ] `update_food` changing the unit leaves `dish_ingredients.quantity` untouched and requires a new `kcal_ref`
- [ ] `create_dish` rejects an empty ingredient list, a duplicated food, and a case-variant duplicate name, all in one transaction that leaves nothing behind on failure
- [ ] `deactivate_dish` sets `active = 0`, keeps ingredients and plan entries, and returns the affected slots of the current **and next** week, relative to the `today` it is given — it must not read the clock, or its behaviour cannot be tested at a fixed date
- [ ] `reactivate_dish` and `reactivate_food` set `active = 1`; `list_dishes(archived=True)` and `list_foods(archived=True)` return the inactive rows
- [ ] Every `Dish` returned by the repository has its `kcal` already resolved through `nutrition.effective_kcal`, so no caller ever sees an unresolved dish
- [ ] `list_dishes` and `list_foods` return active rows only; `count_dishes_by_meal_type` returns a count per `MealType`
- [ ] No module other than `repo.py` imports `sqlite3` — asserted by a test that greps the package

**Verify:** `.venv/bin/pytest tests/test_repo.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

One test per acceptance criterion, driven by the `conn` fixture. Include the architecture guard:

```python
from pathlib import Path


def test_only_repo_imports_sqlite3() -> None:
    offenders = [
        p.name
        for p in Path("meal_planning_bot").rglob("*.py")
        if "import sqlite3" in p.read_text() and p.name not in {"repo.py", "db.py"}
    ]
    assert offenders == []
```

And the transaction guard:

```python
def test_failed_dish_creation_leaves_nothing(conn: sqlite3.Connection) -> None:
    before = conn.execute("SELECT count(*) FROM foods").fetchone()[0]
    with pytest.raises(ValueError):
        repo.create_dish(conn, name="X", meal_type=MealType.LUNCH, kcal=500, ingredients=[])
    assert conn.execute("SELECT count(*) FROM foods").fetchone()[0] == before
    assert conn.execute("SELECT count(*) FROM dishes").fetchone()[0] == 0
```

Run: `.venv/bin/pytest tests/test_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'meal_planning_bot.repo'`

- [ ] **Step 2: Implement the food functions**

Signatures, all taking the connection first:
```python
def create_food(conn, *, name: str, unit: Unit, category: Category, kcal_ref: float) -> Food: ...
def update_food(conn, food_id: int, *, name: str | None = None, unit: Unit | None = None,
                category: Category | None = None, kcal_ref: float | None = None) -> Food: ...
def deactivate_food(conn, food_id: int) -> None: ...   # raises FoodInUse(dish_names)
def reactivate_food(conn, food_id: int) -> Food: ...
def find_foods_by_name(conn, text: str, limit: int = 5) -> list[Food]: ...
def get_food_by_exact_name(conn, name: str) -> Food | None: ...
def list_foods(conn, *, archived: bool = False) -> list[Food]: ...
```

- [ ] **Step 3: Implement the dish functions**

```python
def create_dish(conn, *, name: str, meal_type: MealType,
                ingredients: Sequence[DishIngredient], kcal_override: int | None = None,
                steps: str | None = None) -> Dish: ...
def update_dish(conn, dish_id: int, **fields) -> Dish: ...
def deactivate_dish(conn, dish_id: int, today: date) -> list[tuple[date, int, Slot]]: ...
def reactivate_dish(conn, dish_id: int) -> Dish: ...
def get_dish(conn, dish_id: int) -> Dish: ...
def find_dishes_by_name(conn, text: str, limit: int = 5) -> list[Dish]: ...
def list_dishes(conn, *, archived: bool = False) -> list[Dish]: ...
def count_dishes_by_meal_type(conn) -> dict[MealType, int]: ...
```

`create_dish` validates before any write — empty ingredients and duplicate food IDs raise `ValueError` — then does the whole insert inside `with conn:`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add meal_planning_bot/repo.py tests/test_repo.py
git commit -m "feat(catalog): add the food and dish repository"
```

---

### Task 6: Repository — plans, history and settings

**Goal:** Persist a plan idempotently per week, read back the served history the planner needs, and read and write settings with validation.

**Spec:** `.agent/features/storage/schema.md` (10–13), `.agent/features/week-planner/overview.md` (10), `.agent/features/command-surface/settings.md`

**Files:**
- Modify: `meal_planning_bot/repo.py`
- Create: `tests/test_settings.py`
- Modify: `tests/test_repo.py`

**Acceptance Criteria:**
- [ ] `save_plan` for a `week_start` that already has a plan replaces its entries and keeps one `plans` row
- [ ] `get_plan(week_start)` returns `None` when absent, and a `Plan` with 25 entries when present
- [ ] `scheduled_history(around, days)` returns `ServedRecord`s from stored plans, mapping day 0–4 onto real dates
- [ ] `set_setting` validates against the per-key type and range table and raises `SettingError` otherwise
- [ ] `all_settings()` returns every seeded key with its current value and its default
- [ ] `scheduled_history(around, days)` returns entries from **every** stored plan within the window, including a future week's, so next week's draw sees this week's dishes

**Verify:** `.venv/bin/pytest tests/test_repo.py tests/test_settings.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Cover: saving twice for the same week leaves one plan row and the new entries; `served_history` turns plan day 2 of the week starting 2026-09-14 into 2026-09-16; each setting key rejects a value outside its range; an unknown key raises; `all_settings` returns nine rows.

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL

- [ ] **Step 2: Implement**

```python
SETTING_SPECS: dict[str, SettingSpec] = {
    "daily_kcal_target": IntSpec(default=2000, low=800, high=6000),
    "kcal_tolerance_pct": IntSpec(default=10, low=0, high=50),
    "max_food_repeats_per_day": IntSpec(default=2, low=1, high=5),
    "cooldown_days_breakfast": IntSpec(default=1, low=1, high=60),
    "cooldown_days_snack": IntSpec(default=1, low=1, high=60),
    "cooldown_days_lunch": IntSpec(default=14, low=1, high=60),
    "cooldown_days_dinner": IntSpec(default=1, low=1, high=60),
    "weekly_post_weekday": IntSpec(default=4, low=0, high=6),
    "weekly_post_time": TimeSpec(default="18:00"),
    "daily_post_time": TimeSpec(default="08:00"),
}
```

```python
def save_plan(conn, plan: Plan) -> None: ...
def get_plan(conn, week_start: date) -> Plan | None: ...
def scheduled_history(conn, around: date, days: int = 60) -> list[ServedRecord]: ...
def get_setting(conn, key: str) -> str: ...
def set_setting(conn, key: str, raw: str) -> tuple[str, str]: ...  # (old, new)
def all_settings(conn) -> list[tuple[str, str, str]]: ...          # (key, value, default)
def planner_settings(conn) -> PlannerSettings: ...
```

`save_plan` runs `DELETE FROM plan_entries WHERE plan_id = ?` then re-inserts, inside one `with conn:`, after an `INSERT ... ON CONFLICT(week_start) DO UPDATE SET generated_at = ?, relaxation = ?`.

Add a `SEEDED_SETTINGS` consistency test asserting `SETTING_SPECS.keys() == SEEDED_SETTINGS.keys()` so the two can never drift.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_repo.py tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/repo.py tests/test_repo.py tests/test_settings.py
git commit -m "feat(storage): persist plans, served history and validated settings"
```

---

### Task 7: Planner — constraints and the solver

**Goal:** A pure backtracking solver that fills 25 slots under every hard constraint, deterministic under a seed, bounded by a node cap.

**Spec:** `.agent/features/week-planner/overview.md` (1–7, 9, 11–12), `.agent/features/week-planner/constraints.md`

**Files:**
- Create: `meal_planning_bot/planner.py`, `tests/test_planner.py`, `tests/factories.py`

**Acceptance Criteria:**
- [ ] `solve()` fills all 25 day/slot pairs from the matching meal type
- [ ] The same seed and catalogue produce an identical plan; different seeds produce different plans on a catalogue with slack
- [ ] No day's kcal falls outside target ± tolerance
- [ ] No food appears in more than `max_food_repeats_per_day` dishes on one day
- [ ] No dish appears twice on one day, snack slots included
- [ ] A dish served last Wednesday with a 14-day cooldown never appears this week; Friday-to-Monday counts as three days
- [ ] A catalogue whose only solution requires backtracking is still solved
- [ ] The node cap of 50 000 ends a hopeless search instead of hanging
- [ ] `planner.py` imports neither `sqlite3`, nor `telegram`, nor `datetime.now` — asserted by a test

**Verify:** `.venv/bin/pytest tests/test_planner.py -v` → all pass, under 2 s

**Steps:**

- [ ] **Step 1: Write `tests/factories.py`**

```python
def dish(id: int, meal_type: MealType, kcal: int, foods: Sequence[int] = ()) -> Dish:
    return Dish(
        id=id,
        name=f"d{id}",
        meal_type=meal_type,
        kcal=kcal,
        ingredients=tuple(DishIngredient(food_id=f, quantity=100.0) for f in foods),
    )


def catalogue(per_type: int, kcal: dict[MealType, int]) -> list[Dish]:
    out: list[Dish] = []
    next_id = 1
    for meal_type in MealType:
        for _ in range(per_type):
            out.append(dish(next_id, meal_type, kcal[meal_type], foods=[next_id]))
            next_id += 1
    return out
```

- [ ] **Step 2: Write the failing tests**

Cover every acceptance criterion, one test each. The purity guard:

```python
def test_planner_is_pure() -> None:
    source = Path("meal_planning_bot/planner.py").read_text()
    for forbidden in ("import sqlite3", "from telegram", "import telegram", "datetime.now"):
        assert forbidden not in source
```

The determinism test:

```python
def test_same_seed_same_plan() -> None:
    cat = catalogue(6, {t: 400 for t in MealType})
    a = solve(cat, [], SETTINGS, date(2026, 9, 14), Random(7))
    b = solve(cat, [], SETTINGS, date(2026, 9, 14), Random(7))
    assert a.entries == b.entries
```

Run: `.venv/bin/pytest tests/test_planner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'meal_planning_bot.planner'`

- [ ] **Step 3: Implement the constraint checks**

```python
from meal_planning_bot.models import PlannerSettings

NODE_CAP = 50_000


def day_window(settings: PlannerSettings) -> tuple[int, int]:
    slack = settings.daily_kcal_target * settings.kcal_tolerance_pct // 100
    return settings.daily_kcal_target - slack, settings.daily_kcal_target + slack
```

`_candidate_ok(dish, day_index, day_date, assigned_today, food_counts, last_served, settings)` returns `False` when the dish is already on the day, when adding it would push any of its foods past `max_food_repeats_per_day`, or when `(day_date - last_served[dish.id]).days < settings.cooldown_days[dish.meal_type]`.

- [ ] **Step 4: Implement the search**

Fill days 0→4, slots in `SLOT_ORDER`, shuffling each slot's candidate list with the injected `Random`. Maintain per-day running kcal and prune with the cheapest/dearest remaining sums:

```python
def _prunes(running: int, remaining: Sequence[Slot], pools: Mapping[Slot, Sequence[Dish]],
            low: int, high: int) -> bool:
    cheapest = sum(min(d.kcal for d in pools[s]) for s in remaining)
    dearest = sum(max(d.kcal for d in pools[s]) for s in remaining)
    return running + cheapest > high or running + dearest < low
```

Count every visited node; raise `NodeCapReached` past `NODE_CAP`. Backtrack to the previous slot when a day cannot be completed. `last_served` is seeded from the `ServedRecord` list handed in and updated as the plan is built, so the cooldown applies within the week too.

Public entry point:

```python
def solve(catalogue: Sequence[Dish], history: Sequence[ServedRecord],
          settings: PlannerSettings, week_start: date, rng: Random) -> Plan: ...
```

It raises `Unsatisfiable` rather than relaxing — that is Task 8's job.

- [ ] **Step 5: Implement single-slot re-draw**

```python
def redraw_slot(plan: Plan, catalogue: Sequence[Dish], history: Sequence[ServedRecord],
                settings: PlannerSettings, week_start: date, day: int, slot: Slot,
                rng: Random) -> Plan: ...
```

Holds the other 24 entries fixed, applies the same `_candidate_ok` plus the day window to the single candidate, and raises `Unsatisfiable` when nothing fits.

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/pytest tests/test_planner.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add meal_planning_bot/planner.py tests/test_planner.py tests/factories.py
git commit -m "feat(planner): add the constrained week solver"
```

---

### Task 8: Planner — relaxation ladder and failure diagnosis

**Goal:** When the catalogue cannot satisfy the rules, loosen them in a fixed five-step order, report which step won, and when all fail, say exactly what is missing.

**Spec:** `.agent/features/week-planner/relaxation.md`, `.agent/features/week-planner/overview.md` (3, 7, 8)

**Files:**
- Modify: `meal_planning_bot/planner.py`, `tests/test_planner.py`

**Acceptance Criteria:**
- [ ] `plan_week()` tries steps 0–4 in order and returns at the first success, with `Plan.relaxation` set to that index
- [ ] Step 1 halves every cooldown with a floor of 1; step 2 sets them all to 1; step 3 raises `max_food_repeats_per_day` by one; step 4 doubles `kcal_tolerance_pct`
- [ ] The meal-type rule and the once-per-day rule still hold at step 4
- [ ] A catalogue engineered to fail step N-1 and pass step N reports exactly N, for every N
- [ ] Total failure returns a `PlannerFailure` naming each short meal type with its count and requirement, and stating whether the calorie window is reachable at all

**Verify:** `.venv/bin/pytest tests/test_planner.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Five catalogues, each satisfiable only from a given step onwards, asserting the returned `relaxation`. Plus:

```python
def test_never_relaxed_rules_hold_at_step_four() -> None:
    plan = plan_week(TIGHT_CATALOGUE, HISTORY, SETTINGS, date(2026, 9, 14), Random(1))
    assert plan.relaxation == 4
    by_day: dict[int, list[int]] = defaultdict(list)
    for e in plan.entries:
        by_day[e.day].append(e.dish_id)
        assert SLOT_MEAL_TYPE[e.slot] == dish_by_id[e.dish_id].meal_type
    for dishes in by_day.values():
        assert len(dishes) == len(set(dishes))


def test_failure_names_the_short_meal_type() -> None:
    cat = [d for d in catalogue(6, KCAL) if d.meal_type is not MealType.DINNER]
    with pytest.raises(PlannerFailure) as exc:
        plan_week(cat, [], SETTINGS, date(2026, 9, 14), Random(1))
    assert "dinner" in str(exc.value)
```

Run: `.venv/bin/pytest tests/test_planner.py -v`
Expected: FAIL — `plan_week` and `PlannerFailure` do not exist

- [ ] **Step 2: Implement the ladder**

```python
def _ladder(base: PlannerSettings) -> list[PlannerSettings]:
    halved = {t: max(1, n // 2) for t, n in base.cooldown_days.items()}
    ones = dict.fromkeys(base.cooldown_days, 1)
    return [
        base,
        replace(base, cooldown_days=halved),
        replace(base, cooldown_days=ones),
        replace(base, cooldown_days=ones,
                max_food_repeats_per_day=base.max_food_repeats_per_day + 1),
        replace(base, cooldown_days=ones,
                max_food_repeats_per_day=base.max_food_repeats_per_day + 1,
                kcal_tolerance_pct=base.kcal_tolerance_pct * 2),
    ]


def plan_week(catalogue, history, settings, week_start, rng) -> Plan:
    for step, attempt in enumerate(_ladder(settings)):
        try:
            return replace(solve(catalogue, history, attempt, week_start, rng), relaxation=step)
        except (Unsatisfiable, NodeCapReached):
            continue
    raise PlannerFailure(_diagnose(catalogue, settings))
```

- [ ] **Step 3: Implement `_diagnose`**

Counts active dishes per meal type against the minimum each needs (5 for breakfast, lunch and dinner; 10 for snack, since two slots a day cannot share a dish), and checks whether five dishes at the minimum kcal can reach the window's floor and five at the maximum stay under its ceiling. Returns a structured `PlannerFailure` carrying both findings so `formatting.py` can render them.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_planner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add meal_planning_bot/planner.py tests/test_planner.py
git commit -m "feat(planner): relax constraints in a fixed ladder and diagnose failures"
```

---

### Task 9: Planner invariants under fuzzing, and a realistic catalogue

**Goal:** Prove the solver's guarantees hold across hundreds of generated catalogues and seeds — not only the handful of cases someone thought to write — and prove a real-sized catalogue keeps solving at relaxation 0 week after week.

**Why this task exists:** The solver is the only real algorithm in the project. Example-based tests check the cases you imagined; they cannot tell you that the 14-day lunch cooldown quietly starves a 18-dish lunch catalogue by week six. These tests check invariants, not examples.

**Spec:** `.agent/features/week-planner/constraints.md`, `.agent/features/week-planner/relaxation.md`

**Files:**
- Create: `tests/test_planner_invariants.py`, `tests/fixtures/__init__.py`, `tests/fixtures/realistic_catalogue.py`
- Modify: `tests/factories.py`

**Acceptance Criteria:**
- [ ] `assert_plan_valid()` derives the *effective* settings from `plan.relaxation` by calling `planner._ladder`, so the checker can never drift from the ladder it is checking
- [ ] The generators are mean enough that the sweep actually covers the solver: a dedicated test asserts that across the 200 seeds at least one case fails outright, at least one is solved at a relaxation above 0, and at least a quarter are solved at all. Without this guard a generous generator leaves every case at relaxation 0 and the suite is green while exercising one code path
- [ ] A second guard asserts that at least a quarter of the tiny catalogues genuinely fail, so the brute-force soundness check below actually runs instead of passing by never entering its body
- [ ] Both sweeps share the solver results with the per-seed tests through a cache, so no catalogue is solved twice
- [ ] Over 200 generated (catalogue, seed) pairs, every returned plan satisfies all six invariants: 25 slots filled, slot meal type matches, no dish twice in a day, food repeats within the effective limit, each day's kcal inside the effective window, every cooldown respected against both history and the plan under construction
- [ ] **Soundness:** on small catalogues (3 dishes per meal type, 4 with two snack slots) a brute-force enumeration confirms that every `PlannerFailure` is genuine — no valid plan existed
- [ ] A realistic catalogue (12 breakfasts, 20 snacks, 18 lunches, 18 dinners, plausible kcal) solves at relaxation 0 for 50 consecutive weeks, with each week's result fed back as history
- [ ] Across those 50 weeks, no dish is served more often than the catalogue size allows, and the lunch cooldown never forces a relaxation
- [ ] The 50-week run completes in under 5 seconds on CI

**Verify:** `.venv/bin/pytest tests/test_planner_invariants.py -v --durations=5` → all pass, slowest test under 5 s

**Steps:**

- [ ] **Step 1: Write the invariant checker**

`tests/test_planner_invariants.py`:
```python
from collections import Counter, defaultdict
from datetime import timedelta

from meal_planning_bot.models import SLOT_MEAL_TYPE, SLOT_ORDER, Plan, PlannerSettings
from meal_planning_bot.planner import _ladder, day_window


def assert_plan_valid(plan, catalogue, history, settings, week_start):
    effective = _ladder(settings)[plan.relaxation]
    by_id = {d.id: d for d in catalogue}
    low, high = day_window(effective)

    assert len(plan.entries) == 25
    assert {(e.day, e.slot) for e in plan.entries} == {
        (d, s) for d in range(5) for s in SLOT_ORDER
    }

    last_served = {r.dish_id: r.served_on for r in history}
    by_day = defaultdict(list)
    for entry in sorted(plan.entries, key=lambda e: (e.day, SLOT_ORDER.index(e.slot))):
        dish = by_id[entry.dish_id]
        assert dish.meal_type is SLOT_MEAL_TYPE[entry.slot]
        by_day[entry.day].append(dish)

    for day, dishes in by_day.items():
        day_date = week_start + timedelta(days=day)

        ids = [d.id for d in dishes]
        assert len(ids) == len(set(ids)), f"day {day} repeats a dish"

        foods = Counter(i.food_id for d in dishes for i in d.ingredients)
        worst = max(foods.values(), default=0)
        assert worst <= effective.max_food_repeats_per_day, f"day {day} food repeat {worst}"

        total = sum(d.kcal for d in dishes)
        assert low <= total <= high, f"day {day} kcal {total} outside [{low}, {high}]"

        for dish in dishes:
            previous = last_served.get(dish.id)
            if previous is not None:
                gap = (day_date - previous).days
                assert gap >= effective.cooldown_days[dish.meal_type], (
                    f"dish {dish.id} repeated after {gap} days"
                )
            last_served[dish.id] = day_date
```

- [ ] **Step 2: Write the fuzz test and watch it run**

```python
import pytest
from random import Random

from meal_planning_bot.planner import PlannerFailure, plan_week


def generate_catalogue(rng: Random):
    per_type = {
        MealType.BREAKFAST: rng.randint(5, 12),
        MealType.SNACK: rng.randint(10, 22),
        MealType.LUNCH: rng.randint(5, 18),
        MealType.DINNER: rng.randint(5, 18),
    }
    food_pool = list(range(1, rng.randint(8, 40)))
    dishes, next_id = [], 1
    for meal_type, count in per_type.items():
        base = {MealType.BREAKFAST: 400, MealType.SNACK: 180,
                MealType.LUNCH: 700, MealType.DINNER: 540}[meal_type]
        for _ in range(count):
            dishes.append(
                dish(
                    next_id,
                    meal_type,
                    kcal=base + rng.randint(-120, 120),
                    foods=rng.sample(food_pool, k=min(len(food_pool), rng.randint(1, 4))),
                )
            )
            next_id += 1
    return dishes


@pytest.mark.parametrize("seed", range(200))
def test_every_returned_plan_is_valid(seed: int) -> None:
    rng = Random(seed)
    catalogue = generate_catalogue(rng)
    week_start = date(2026, 9, 14)
    try:
        plan = plan_week(catalogue, [], DEFAULT_SETTINGS, week_start, Random(seed))
    except PlannerFailure:
        return
    assert_plan_valid(plan, catalogue, [], DEFAULT_SETTINGS, week_start)
```

Run: `.venv/bin/pytest tests/test_planner_invariants.py -v`
Expected: any invariant the solver violates fails here loudly. Fix `planner.py`, not the checker.

- [ ] **Step 3: Write the soundness test**

```python
def brute_force_exists(catalogue, settings, week_start) -> bool:
    """Exhaustive search over a deliberately tiny catalogue."""
    pools = {s: [d for d in catalogue if d.meal_type is SLOT_MEAL_TYPE[s]] for s in SLOT_ORDER}
    ...


@pytest.mark.parametrize("seed", range(30))
def test_failures_are_genuine(seed: int) -> None:
    rng = Random(seed)
    catalogue = tiny_catalogue(rng)
    week_start = date(2026, 9, 14)
    try:
        plan_week(catalogue, [], DEFAULT_SETTINGS, week_start, Random(seed))
    except PlannerFailure:
        loosest = _ladder(DEFAULT_SETTINGS)[-1]
        assert not brute_force_exists(catalogue, loosest, week_start)
```

Keep the tiny catalogue at three dishes per meal type (four snacks) so the enumeration finishes.

- [ ] **Step 4: Write the realistic catalogue fixture**

`tests/fixtures/realistic_catalogue.py` holds the named dishes with plausible kcal and shared foods — rice, chicken, eggs, oats, yoghurt — so the food-repeat constraint is actually exercised rather than trivially satisfied by unique ingredients.

- [ ] **Step 5: Write the long-run test**

```python
def test_fifty_weeks_never_need_relaxation() -> None:
    catalogue = REALISTIC_CATALOGUE
    history: list[ServedRecord] = []
    week_start = date(2026, 1, 5)
    served = Counter()

    for week in range(50):
        plan = plan_week(catalogue, history, DEFAULT_SETTINGS, week_start, Random(week))
        assert plan.relaxation == 0, f"week {week} needed relaxation {plan.relaxation}"
        assert_plan_valid(plan, catalogue, history, DEFAULT_SETTINGS, week_start)
        for entry in plan.entries:
            history.append(ServedRecord(entry.dish_id, week_start + timedelta(days=entry.day)))
            served[entry.dish_id] += 1
        history = [r for r in history if (week_start - r.served_on).days <= 60]
        week_start += timedelta(days=7)

    assert served[min(served, key=served.get)] > 0, "some dish was never served"
```

If this test fails, the finding is real and belongs in the spec: either the default `cooldown_days_lunch` of 14 is too strict for an 18-dish lunch catalogue, or the catalogue minimum in `_diagnose` is wrong. Fix whichever is wrong and update `.agent/features/week-planner/relaxation.md` in the same commit.

- [ ] **Step 6: Run the whole planner suite**

Run: `.venv/bin/pytest tests/test_planner.py tests/test_planner_invariants.py -v --durations=5`
Expected: PASS, slowest test under 5 s

- [ ] **Step 7: Commit**

```bash
git add tests/test_planner_invariants.py tests/fixtures tests/factories.py
git commit -m "test(planner): check invariants under fuzzing and over fifty weeks"
```

---

### Task 10: Shopping list aggregation

**Goal:** A pure function turning a week's dishes into per-food totals grouped by category, with the documented rounding.

**Spec:** `.agent/features/shopping-list/overview.md` (1–7)

**Files:**
- Create: `meal_planning_bot/shopping.py`, `tests/test_shopping.py`

**Acceptance Criteria:**
- [ ] A food used by three dishes sums across all three; a dish drawn on two days counts twice
- [ ] Categories come out in `CATEGORY_ORDER`; foods inside a category sort case-insensitively by name
- [ ] `g` and `ml` round to a whole number; `unit` rounds to one decimal and drops a trailing `.0`
- [ ] Categories with no foods are omitted
- [ ] Calling twice with the same input returns equal results and mutates nothing

**Verify:** `.venv/bin/pytest tests/test_shopping.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
def test_counts_a_dish_drawn_twice() -> None:
    plan = plan_with(entries=[(0, Slot.LUNCH, 1), (1, Slot.LUNCH, 1)])
    groups = aggregate(plan, {1: dish_with(foods={10: 150.0})}, {10: FOOD_RICE})
    assert groups[0].lines[0].quantity == "300"
```

Plus one test per remaining criterion.

Run: `.venv/bin/pytest tests/test_shopping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'meal_planning_bot.shopping'`

- [ ] **Step 2: Implement**

```python
@dataclass(frozen=True)
class ShoppingLine:
    food_name: str
    quantity: str
    unit: Unit


@dataclass(frozen=True)
class ShoppingGroup:
    category: Category
    lines: tuple[ShoppingLine, ...]


def _render_quantity(total: float, unit: Unit) -> str:
    if unit is Unit.UNIT:
        rounded = round(total, 1)
        return f"{rounded:g}"
    return str(round(total))


def aggregate(plan: Plan, dishes: Mapping[int, Dish],
              foods: Mapping[int, Food]) -> tuple[ShoppingGroup, ...]: ...
```

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_shopping.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/shopping.py tests/test_shopping.py
git commit -m "feat(shopping): aggregate a week's ingredients by category"
```

---

### Task 11: Spanish message formatting

**Goal:** Every user-visible string, in one module, rendering the plan, the day, the shopping list, dish cards, help, errors, and the relaxation notice.

**Spec:** `.agent/features/command-surface/overview.md` (2–6, 10–11), `.agent/features/shopping-list/overview.md` (11), `.agent/features/week-planner/relaxation.md` (9), `.agent/features/catalog/overview.md` (3–6)

**Files:**
- Create: `meal_planning_bot/formatting.py`, `tests/test_formatting.py`

**Acceptance Criteria:**
- [ ] `render_plan` shows five days, each with its five slots, dish names, kcal, and the day's total
- [ ] `render_day` shows one day's five slots
- [ ] `render_shopping` groups by category and splits at a category boundary when over 4 000 characters, returning a list of messages
- [ ] `render_dish` shows meal type, kcal, ingredients with quantity and unit, and steps when present
- [ ] `render_dishes_page` paginates at twenty and reports the page number
- [ ] `render_relaxation_notice` returns text only when the step is above zero
- [ ] `render_help` lists every command registered in `COMMANDS`
- [ ] No other module under `meal_planning_bot/` contains a non-ASCII string literal — asserted by a test

**Verify:** `.venv/bin/pytest tests/test_formatting.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Include the localisation guard:

```python
def test_spanish_lives_only_in_formatting() -> None:
    for path in Path("meal_planning_bot").rglob("*.py"):
        if path.name == "formatting.py":
            continue
        for line in path.read_text().splitlines():
            stripped = line.split("#", 1)[0]
            assert stripped.isascii(), f"non-ASCII literal in {path}: {line}"
```

And the split test:

```python
def test_shopping_splits_at_a_category_boundary() -> None:
    messages = render_shopping(huge_groups())
    assert len(messages) > 1
    assert all(len(m) <= 4000 for m in messages)
    assert not any(m.startswith("  ") for m in messages)
```

Run: `.venv/bin/pytest tests/test_formatting.py -v`
Expected: FAIL

- [ ] **Step 2: Implement**

Day names `Lunes`–`Viernes`, slot labels `Desayuno`, `Snack 1`, `Comida`, `Snack 2`, `Cena`, category labels `Frutas y verduras`, `Carne y pescado`, `Lácteos y huevos`, `Panadería`, `Congelados`, `Despensa`, `Bebidas`, `Otros`. Every function returns `str` or `list[str]`; none touches the database.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_formatting.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/formatting.py tests/test_formatting.py
git commit -m "feat(commands): add Spanish message rendering"
```

---

### Task 12: Access control

**Goal:** Decorators that drop every update from a non-allow-listed user or an unknown chat without replying, and restrict the mutating commands to private chats.

**Spec:** `.agent/features/access-control/overview.md`

**Files:**
- Create: `meal_planning_bot/access.py`, `tests/test_access.py`

**Acceptance Criteria:**
- [ ] An update from a user ID outside the allow-list produces no reply and logs the ID at INFO
- [ ] An allow-listed user in a chat that is neither the configured group nor a private chat produces no reply
- [ ] `/myid` bypasses the allow-list in a private chat only
- [ ] A `private_only` handler called from the group replies with the redirect message and does not run
- [ ] Neither the token, the allow-list, nor the group chat ID appears in any log record — asserted with `caplog`

**Verify:** `.venv/bin/pytest tests/test_access.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Use lightweight fakes rather than the Telegram library's objects:

```python
@dataclass
class FakeChat:
    id: int
    type: str


@dataclass
class FakeUpdate:
    effective_user: SimpleNamespace
    effective_chat: FakeChat
    replies: list[str] = field(default_factory=list)
```

Run: `.venv/bin/pytest tests/test_access.py -v`
Expected: FAIL

- [ ] **Step 2: Implement**

```python
def allowed(config: Config) -> Callable[[Handler], Handler]: ...
def private_only(handler: Handler) -> Handler: ...
```

`allowed` checks `update.effective_user.id in config.allowed_user_ids` and that `update.effective_chat.id == config.group_chat_id or update.effective_chat.type == "private"`, returning without a reply on either failure.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_access.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/access.py tests/test_access.py
git commit -m "feat(access): gate every handler on the allow-list and chat"
```

---

### Task 13: Consultation handlers

**Goal:** `/start`, `/help`, `/myid`, `/plan`, `/today`, `/shopping`, with the documented behaviour when no plan exists and on a weekend.

**Spec:** `.agent/features/command-surface/overview.md` (2–6, 9–11), `.agent/features/shopping-list/overview.md` (8–9)

**Files:**
- Create: `meal_planning_bot/handlers/__init__.py`, `meal_planning_bot/handlers/help.py`, `meal_planning_bot/handlers/plan.py`, `tests/test_handlers.py`

**Acceptance Criteria:**
- [ ] `/plan` with no plan for the current week replies with the "no plan" text suggesting `/regenerate`
- [ ] `/today` on a Saturday or Sunday replies that the weekend is not planned
- [ ] `/shopping` renders the aggregated list for the stored plan and splits into several messages when long
- [ ] `/help` and an unknown command both return the help text
- [ ] The current date is injected, not read from the clock, so the weekend test needs no freezing library

**Verify:** `.venv/bin/pytest tests/test_handlers.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Drive the handlers with the fakes from Task 12 plus the in-memory `conn` fixture, passing `today` explicitly.

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: FAIL

- [ ] **Step 2: Implement**

Each handler resolves `week_start = today - timedelta(days=today.weekday())`, reads through `repo`, renders through `formatting`, and replies in the chat it was called from. `today` comes from a `clock: Callable[[], date]` stored on `context.bot_data`, so tests inject a fixed date.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/handlers tests/test_handlers.py
git commit -m "feat(commands): add the consultation handlers"
```

---

### Task 14: Plan-changing handlers

**Goal:** `/regenerate` and `/swap`, including Spanish and numeric argument parsing, the optional `siguiente` week, and the "no valid candidate" path.

**Spec:** `.agent/features/week-planner/overview.md` (10–12), `.agent/features/command-surface/overview.md` (7–9)

**Files:**
- Modify: `meal_planning_bot/handlers/plan.py`, `tests/test_handlers.py`

**Acceptance Criteria:**
- [ ] `/regenerate` replaces the week's entries and replies with the plan plus the relaxation notice when the step is above zero
- [ ] `/swap lunes cena` and `/swap 1 cena` both resolve to day 0, slot `dinner`, current week
- [ ] `/swap lunes cena siguiente` resolves to next Monday's week
- [ ] `/regenerate siguiente` draws next week and leaves the current week's plan untouched
- [ ] Unparseable arguments reply with the accepted forms and change nothing
- [ ] A slot with no valid candidate replies as such and leaves the existing assignment
- [ ] Neither command posts to the group when called from a private chat

**Verify:** `.venv/bin/pytest tests/test_handlers.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["lunes", "cena"], (0, Slot.DINNER)),
        (["1", "cena"], (0, Slot.DINNER)),
        (["VIERNES", "Snack2"], (4, Slot.SNACK2)),
        (["lunes", "cena", "siguiente"], (0, Slot.DINNER)),
    ],
)
def test_swap_argument_parsing(args: list[str], expected: tuple[int, Slot]) -> None:
    day, slot, _is_next = parse_swap_args(args)
    assert (day, slot) == expected


def test_swap_resolves_the_week() -> None:
    assert parse_swap_args(["lunes", "cena"])[2] is False
    assert parse_swap_args(["lunes", "cena", "siguiente"])[2] is True


@pytest.mark.parametrize("args", [[], ["lunes"], ["sabado", "cena"], ["1", "merienda"], ["9", "cena"]])
def test_swap_rejects_bad_arguments(args: list[str]) -> None:
    with pytest.raises(ArgumentError):
        parse_swap_args(args)
```

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: FAIL

- [ ] **Step 2: Implement**

`parse_swap_args` maps `lunes|martes|miercoles|miércoles|jueves|viernes` and `1`–`5` to day 0–4, `desayuno|snack1|comida|snack2|cena` to the `Slot` enum, and an optional trailing `siguiente` to the next-week flag — case-insensitively and accent-insensitively. `/plan`, `/shopping` and `/regenerate` share `weeks.resolve_week` for the same keyword.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/handlers/plan.py tests/test_handlers.py
git commit -m "feat(planner): add /regenerate and /swap"
```

---

### Task 15: Catalogue browsing handlers

**Goal:** `/dishes`, `/dish`, `/foods`, their `archivados` variants, and `/restore`, with pagination and the fuzzy-match fallback.

**Spec:** `.agent/features/catalog/overview.md` (3–6)

**Files:**
- Create: `meal_planning_bot/handlers/catalog.py`
- Modify: `tests/test_handlers.py`

**Acceptance Criteria:**
- [ ] `/dishes` paginates at twenty with working next and previous inline buttons
- [ ] `/dish <exact name>` returns the full card
- [ ] `/dish <partial>` returns up to five inline buttons, and tapping one returns that card
- [ ] `/dish <no match>` says so
- [ ] `/foods` groups by category in `CATEGORY_ORDER`, showing each food's unit and `kcal_ref`
- [ ] `/dishes archivados` and `/foods archivados` list the inactive rows with the same pagination
- [ ] `/restore <name>` reactivates an archived dish or food, offers buttons when the name matches more than one, and says so when it matches none
- [ ] `/dish` shows whether the calories are computed or overridden

**Verify:** `.venv/bin/pytest tests/test_handlers.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** — one per criterion, including a callback-query test for the pagination button and for the fuzzy-match button.

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: FAIL

- [ ] **Step 2: Implement** — callback data is `dishes:<page>:<archived>`, `dish:<id>` and `restore:<kind>:<id>`, parsed by one small function that is unit-tested on its own.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/handlers/catalog.py tests/test_handlers.py
git commit -m "feat(catalog): add the browsing handlers"
```

---

### Task 16: Catalogue wizards

**Goal:** The six conversation flows that create and edit dishes and foods, writing nothing until the final confirmation.

**Spec:** `.agent/features/catalog/wizards.md`

**Files:**
- Create: `meal_planning_bot/handlers/wizards.py`, `tests/test_wizards.py`

**Acceptance Criteria:**
- [ ] `/newdish` walks name → meal type → ingredients → steps → calories → summary → confirm, and writes only on confirm
- [ ] The calorie step shows the value computed from the ingredients, with an `Accept` button storing no override and a typed number storing one
- [ ] An unknown food name during ingredient collection offers inline creation (unit, category, `kcal_ref`), pre-filled from the seed when the lower-cased name matches an entry exactly, and then continues
- [ ] An ambiguous food name offers up to five buttons instead of guessing
- [ ] A non-positive or non-numeric quantity re-asks the same step
- [ ] `/cancel` and `Discard` both leave the database untouched
- [ ] Starting a second wizard replaces the first with a notice
- [ ] The confirmation write is one transaction: a forced failure leaves neither the dish nor the inline-created food
- [ ] `/editdish` changes exactly one field; `/deletedish` and `/deletefood` require explicit confirmation

**Verify:** `.venv/bin/pytest tests/test_wizards.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**

Drive the `ConversationHandler` state functions directly — call each state's callback with a fake update and assert the returned next state and the reply. Do not start a real `Application`.

```python
async def test_newdish_writes_only_on_confirm(conn, wizard) -> None:
    await wizard.send("/newdish")
    await wizard.send("Pollo al horno")
    await wizard.tap("meal:lunch")
    await wizard.send("pollo 200")
    await wizard.tap("ing:done")
    await wizard.tap("steps:skip")
    await wizard.tap("kcal:accept")
    assert conn.execute("SELECT count(*) FROM dishes").fetchone()[0] == 0
    await wizard.tap("confirm:yes")
    assert conn.execute("SELECT count(*) FROM dishes").fetchone()[0] == 1
```

Run: `.venv/bin/pytest tests/test_wizards.py -v`
Expected: FAIL

- [ ] **Step 2: Implement the dish wizard** — states `NAME`, `MEAL_TYPE`, `INGREDIENT`, `NEW_FOOD_UNIT`, `NEW_FOOD_CATEGORY`, `NEW_FOOD_KCAL`, `STEPS`, `KCAL`, `CONFIRM`. Draft state lives in `context.user_data["draft"]`; nothing reaches `repo` before `CONFIRM`.

- [ ] **Step 3: Implement the food wizards and the delete confirmations.**

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_wizards.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add meal_planning_bot/handlers/wizards.py tests/test_wizards.py
git commit -m "feat(catalog): add the dish and food wizards"
```

---

### Task 17: Settings handlers

**Goal:** `/settings` and `/set`, validating against `SETTING_SPECS` and confirming with the old and new values.

**Spec:** `.agent/features/command-surface/settings.md` (2–8, 10)

**Files:**
- Create: `meal_planning_bot/handlers/settings.py`
- Modify: `tests/test_settings.py`

**Acceptance Criteria:**
- [ ] `/settings` lists every key with its current value and default
- [ ] `/set daily_kcal_target 2200` stores it and confirms with `2000 → 2200`
- [ ] An unknown key replies with the valid key list and changes nothing
- [ ] An out-of-range value replies with the accepted range and changes nothing
- [ ] `/set weekly_post_weekday 6` moves the planning post to Sunday and re-registers the job
- [ ] `/set` from the group is rejected by `private_only`
- [ ] No environment-provided value is reachable through `/set`

**Verify:** `.venv/bin/pytest tests/test_settings.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests**, including `assert set(SETTING_SPECS) & {"token", "group_chat_id", "db_path", "timezone"} == set()`.

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL

- [ ] **Step 2: Implement.** After a successful write of `weekly_post_time` or `daily_post_time`, call the scheduler's re-registration hook stored on `context.bot_data["reschedule"]`.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/handlers/settings.py tests/test_settings.py
git commit -m "feat(commands): add /settings and /set"
```

---

### Task 18: Scheduler and startup catch-up

**Goal:** The Friday planning post for **next** week, the weekday digest for the current week, timezone-aware times, re-registration on a settings change, and a catch-up when the bot starts with a week unplanned.

**Spec:** `.agent/features/notifications/overview.md`

**Files:**
- Create: `meal_planning_bot/scheduler.py`, `tests/test_scheduler.py`

**Acceptance Criteria:**
- [ ] Every job time is a `datetime.time` carrying `ZoneInfo(config.timezone)`
- [ ] Across a DST boundary the job still fires at the configured local time — asserted by comparing UTC offsets in January and July
- [ ] The daily job is registered for days 0–4 only; the weekly job for `weekly_post_weekday` only
- [ ] The weekly job draws the week starting the **following** Monday and labels the post with that date
- [ ] The weekly job passes the current week's stored entries as history, so the cooldown spans the boundary
- [ ] Starting on a Wednesday with no current-week plan generates one, posts it, then posts the day
- [ ] Starting on a Saturday with next week unplanned generates and posts next week
- [ ] Starting when both weeks already have plans posts nothing
- [ ] A failed send logs and does not retry
- [ ] Changing a post time re-registers only the affected job
- [ ] Scheduled sends target `config.group_chat_id` and nothing else

**Verify:** `.venv/bin/pytest tests/test_scheduler.py -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** against a fake job queue recording `(callback, time, days)` tuples and a fake bot recording `(chat_id, text)`.

Run: `.venv/bin/pytest tests/test_scheduler.py -v`
Expected: FAIL

- [ ] **Step 2: Implement**

```python
def parse_local_time(raw: str, tz: ZoneInfo) -> time:
    hour, minute = (int(p) for p in raw.split(":"))
    return time(hour=hour, minute=minute, tzinfo=tz)


def register_jobs(job_queue, conn, config) -> None: ...
def reschedule(job_queue, conn, config, key: str) -> None: ...
async def weekly_job(context) -> None: ...      # draws weeks.next_week_start(today)
async def daily_job(context) -> None: ...       # reads weeks.current_week_start(today)
def startup_catch_up(conn, config, today: date) -> list[Plan]: ...
```

`register_jobs` names its jobs `weekly` and `daily` so `reschedule` can find and replace one by name.

- [ ] **Step 3: Run to verify pass**

Run: `.venv/bin/pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/scheduler.py tests/test_scheduler.py
git commit -m "feat(notifications): schedule the weekly post and the daily digest"
```

---

### Task 19: Entry point

**Goal:** Wire config, database, handlers, scheduler and the registered command list into a process that long-polls.

**Spec:** `.agent/features/command-surface/overview.md` (1), `.agent/features/access-control/overview.md` (2)

**Files:**
- Create: `meal_planning_bot/__main__.py`, `meal_planning_bot/telegram_bridge.py`
- Modify: `tests/test_handlers.py`

**Acceptance Criteria:**
- [ ] Every handler except `/myid` is wrapped in `allowed(config)` — asserted by a test that walks the registered handler list
- [ ] The command list passed to `setMyCommands` matches `formatting.COMMANDS` exactly
- [ ] Logging is configured at `config.log_level` and the token never appears in a log record
- [ ] `python -m meal_planning_bot` with a missing required variable exits non-zero printing the variable name

**Verify:** `.venv/bin/pytest tests/test_handlers.py -v` and `MEALBOT_DB_PATH=/tmp/x.db .venv/bin/python -m meal_planning_bot; echo $?` → `2` with `TELEGRAM_BOT_TOKEN is required`

**Steps:**

- [ ] **Step 1: Write the failing wrapping test**

```python
def test_every_handler_is_gated() -> None:
    app = build_application(TEST_CONFIG, conn)
    for group in app.handlers.values():
        for handler in group:
            name = getattr(handler.callback, "__name__", "")
            assert name == "myid" or getattr(handler.callback, "__access_gated__", False)
```

`allowed` sets `__access_gated__ = True` on the wrapper.

Run: `.venv/bin/pytest tests/test_handlers.py -v`
Expected: FAIL

- [ ] **Step 2: Implement `build_application(config, conn)`** returning a configured `Application`, and a `main()` that loads config, opens the database, runs `startup_catch_up`, registers jobs, and calls `run_polling()`. Catch `ConfigError` in `main()`, print it to stderr and `sys.exit(2)`.

- [ ] **Step 3: Run both verifications**

- [ ] **Step 4: Commit**

```bash
git add meal_planning_bot/__main__.py tests/test_handlers.py
git commit -m "feat(repo): wire the application entry point"
```

---

### Task 20: End-to-end integration suite and coverage gate

**Goal:** Drive the fully assembled application — real SQLite file, real handler registration, real `ConversationHandler` state machine — through a complete user journey against a fake Telegram transport, and put a coverage floor in CI.

**Why this task exists:** Every test up to here is a unit test, and unit tests are structurally blind to the bugs that actually ship: a handler registered in the wrong group, a wizard whose callback data does not match the button it rendered, a `bot_data` key written in one module and read under a different name, a plan saved but read back with the days off by one. This suite is the only thing that exercises the seams.

**Spec:** all of `.agent/features/**` — this task asserts the features work together, not in isolation

**Files:**
- Create: `tests/fakes.py`, `tests/test_integration.py`
- Modify: `meal_planning_bot/__main__.py` (injectable bot and clock), `.agent/features/command-surface/overview.md`, `.github/workflows/ci.yml`, `requirements-dev.txt`, `pyproject.toml`

**Acceptance Criteria:**
- [ ] `FakeBot` records every `send_message`, `edit_message_text` and `answer_callback_query` as `(chat_id, text, markup)` tuples, and raises on any method the code calls that the fake has not implemented — so a new Telegram call cannot slip through untested
- [ ] The database is a real file under `tmp_path`, so the PRAGMAs, WAL and the migrations run exactly as in production
- [ ] **Full journey in one test:** empty database → six dishes created through the `/newdish` wizard (creating foods inline) → `/regenerate` → `/plan` lists 25 dishes → `/shopping` totals match a figure computed by hand in the test → `/swap martes cena` changes exactly one entry → `/shopping` changes accordingly → `/today` matches that day's row of `/plan`
- [ ] **Persistence across a restart:** a second `build_application` over the same file returns the same plan and the same catalogue
- [ ] **Access:** the same journey replayed from a user ID outside the allow-list produces zero calls on `FakeBot`
- [ ] **Private-only:** `/newdish` from the group chat replies with the redirect and starts no conversation
- [ ] **Scheduled jobs:** invoking `weekly_job` and `daily_job` directly posts to `config.group_chat_id` and to no other chat
- [ ] **Empty catalogue:** `/regenerate` on an empty database replies with the `PlannerFailure` diagnosis naming all four meal types, and writes no plan
- [ ] Coverage is measured and CI fails below 85 %, with `meal_planning_bot/__main__.py` excluded from the denominator
- [ ] `meal_planning_bot/telegram_bridge.py` is NOT excluded. It adapts real `telegram.Update` objects to the handlers' Protocols and converts keyboards, which is the seam most likely to be wrong in production and exactly what this suite drives real `Update` objects through. Only the process wiring in `__main__.py` is exempt

**Verify:** `.venv/bin/pytest tests/test_integration.py -v` → all pass; `.venv/bin/pytest --cov=meal_planning_bot --cov-report=term-missing --cov-fail-under=85` → pass

**Steps:**

- [ ] **Step 1: Add the test dependencies**

`requirements-dev.txt` gains:
```
pytest-asyncio==0.25.2
pytest-cov==6.0.0
```

`pyproject.toml` gains:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
asyncio_mode = "auto"

[tool.coverage.run]
source = ["meal_planning_bot"]
omit = ["meal_planning_bot/__main__.py"]
```

- [ ] **Step 2: Write `tests/fakes.py`**

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Sent:
    chat_id: int
    text: str
    markup: Any = None


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.edited: list[Sent] = []
        self.answered: list[str] = []

    async def send_message(self, chat_id: int, text: str, reply_markup: Any = None,
                           **kwargs: Any) -> None:
        self.sent.append(Sent(chat_id, text, reply_markup))

    async def edit_message_text(self, text: str, chat_id: int = 0, message_id: int = 0,
                                reply_markup: Any = None, **kwargs: Any) -> None:
        self.edited.append(Sent(chat_id, text, reply_markup))

    async def answer_callback_query(self, callback_query_id: str, **kwargs: Any) -> None:
        self.answered.append(callback_query_id)

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"FakeBot has no {name}(); add it to the fake deliberately")


@dataclass
class Driver:
    """Feeds updates into a real Application and exposes what the bot said."""

    app: Any
    bot: FakeBot
    chat_id: int
    user_id: int
    _message_id: int = field(default=0)

    async def send(self, text: str) -> str: ...
    async def tap(self, callback_data: str) -> str: ...

    @property
    def last(self) -> str:
        return self.bot.sent[-1].text if self.bot.sent else self.bot.edited[-1].text
```

`send` and `tap` build a real `telegram.Update` with a `Message` or `CallbackQuery`, `await self.app.process_update(update)`, and return `self.last`. Building real `Update` objects rather than fakes is deliberate: it is what catches a handler filter that does not match.

- [ ] **Step 3: Write the journey test and watch it fail**

```python
async def test_full_journey(tmp_path) -> None:
    conn = open_database(tmp_path / "mealbot.db")
    bot = FakeBot()
    app = build_application(TEST_CONFIG, conn, bot=bot, clock=lambda: date(2026, 9, 15))
    user = Driver(app, bot, chat_id=TEST_CONFIG.allowed_user_ids_one, user_id=..., ...)

    await create_dish(user, "Tostada con aguacate", "breakfast", 380,
                      [("pan", 80), ("aguacate", 100)])
    ...   # six dishes, enough for one of each slot

    assert "no hay plan" in (await user.send("/plan")).lower()

    await user.send("/regenerate")
    plan_text = await user.send("/plan")
    assert plan_text.count("kcal") == 30      # 25 dishes + 5 day totals

    shopping = await user.send("/shopping")
    assert "Pan: 400 g" in shopping            # 80 g × 5 breakfasts

    before = await user.send("/plan")
    await user.send("/swap martes cena")
    after = await user.send("/plan")
    assert differing_lines(before, after) == 1
```

Run: `.venv/bin/pytest tests/test_integration.py -v`
Expected: FAIL — `build_application` does not yet accept `bot=` and `clock=`

- [ ] **Step 4: Make the entry point injectable**

Change `build_application(config, conn)` from Task 19 to `build_application(config, conn, *, bot=None, clock=date.today)`. When `bot` is given, pass it to `ApplicationBuilder().bot(bot)`; store `clock` in `bot_data["clock"]`. This is the only production change this task makes, and it exists so the application can be assembled in a test without a network.

Update `.agent/features/command-surface/overview.md` with a requirement stating that the application is constructed with an injectable bot and clock — this is observable structure the spec should own.

- [ ] **Step 5: Write the remaining integration tests**

One test each for: restart persistence, the non-allow-listed replay asserting `bot.sent == []`, `/newdish` from the group, the two scheduled jobs asserting every recorded `chat_id` equals the group, and `/regenerate` on an empty database.

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 7: Add the coverage gate to CI**

In `.github/workflows/ci.yml`, replace the `pytest` step with:
```yaml
      - run: pytest --cov=meal_planning_bot --cov-report=term-missing --cov-fail-under=85
```

Run it locally first. If a module sits well below the floor, that is information: either it needs a test or it is dead code that should be deleted. Do not lower the floor to make it pass.

- [ ] **Step 8: Commit**

```bash
git add tests/fakes.py tests/test_integration.py requirements-dev.txt pyproject.toml \
        .github/workflows/ci.yml meal_planning_bot/__main__.py .agent/features/command-surface/overview.md
git commit -m "test(repo): add the end-to-end integration suite and a coverage floor"
```

---

### Task 21: Container image and release pipeline

**Goal:** A slim non-root image, a GHCR build-and-push workflow, and the `spec-update-check` gate.

**Spec:** `AGENTS.md → AI documentation`, `.agent/conventions.md → Audit and verification`

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `.github/workflows/build-and-push.yml`, `.github/workflows/spec-update-check.yml`

**Acceptance Criteria:**
- [ ] `docker build -t meal_planning_bot:dev .` succeeds and the image runs as UID 1000
- [ ] `docker run --rm meal_planning_bot:dev` exits 2 with `TELEGRAM_BOT_TOKEN is required`
- [ ] The build workflow pushes to `ghcr.io/${{ github.repository }}` on `main` and on `v*` tags, and builds without pushing on pull requests
- [ ] `spec-update-check` fails a pull request that changes `meal_planning_bot/` without changing `.agent/features/`, and passes when the label `spec:not-needed` is applied
- [ ] The GHCR package is set to public visibility

**Verify:** `docker build -t meal_planning_bot:dev . && docker run --rm meal_planning_bot:dev; echo $?` → `2`

**Steps:**

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY meal_planning_bot/ /app/meal_planning_bot/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The database lives on a mounted volume owned by this user. It must be local
# storage: SQLite locking is unreliable over NFS and SMB.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin bot \
    && mkdir -p /data && chown 1000:1000 /data
USER 1000

VOLUME ["/data"]
ENTRYPOINT ["python3", "-m", "meal_planning_bot"]
```

- [ ] **Step 2: Add `.dockerignore`**

```
.git
.venv
tests
docs
.agent
.github
__pycache__
*.db
```

- [ ] **Step 3: Add the build workflow** — `docker/login-action@v3` against `ghcr.io` with `GITHUB_TOKEN`, `docker/metadata-action@v5` with `type=sha,prefix=`, `type=ref,event=branch`, `type=semver,pattern={{version}}` and `{{major}}.{{minor}}`, then `docker/build-push-action@v6` pushing only when the event is not a pull request.

- [ ] **Step 4: Add `spec-update-check`**

```yaml
name: spec-update-check

on:
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    if: "!contains(github.event.pull_request.labels.*.name, 'spec:not-needed')"
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Require a spec change alongside a source change
        run: |
          base="${{ github.event.pull_request.base.sha }}"
          changed=$(git diff --name-only "$base" HEAD)
          echo "$changed"
          if echo "$changed" | grep -q '^meal_planning_bot/' && ! echo "$changed" | grep -q '^\.agent/features/'; then
            echo "::error::meal_planning_bot/ changed without a matching .agent/features/ update"
            exit 1
          fi
```

- [ ] **Step 5: Verify locally, then push and make the package public**

```bash
docker build -t meal_planning_bot:dev .
docker run --rm meal_planning_bot:dev; echo $?     # expect 2
git add Dockerfile .dockerignore .github/workflows
git commit -m "ci(repo): build and publish the container image"
git push origin main
```

After the first successful push, set the GHCR package visibility to public:
```bash
gh api -X PATCH /user/packages/container/telegram-meal-planning-bot --field visibility=public
```
If the endpoint refuses, set it in the package settings page on GitHub. Verify anonymously:
```bash
docker pull ghcr.io/OWNER/telegram-meal-planning-bot:main
```

---

## Execution order

| Task | Depends on | Can run in parallel with |
|------|------------|--------------------------|
| 1 Scaffolding | — | — |
| 2 Config | 1 | 3 |
| 3 Models, DB, migrations | 1 | 2 |
| 4 Calories and weeks | 3 | — |
| 5 Repo: foods and dishes | 4 | 6, 7, 10 |
| 6 Repo: plans and settings | 4 | 5, 7, 10 |
| 7 Planner: solver | 3 | 5, 6, 10 |
| 8 Planner: relaxation | 7 | 5, 6, 10 |
| 9 Planner: invariants and fuzzing | 8 | 5, 6, 10 |
| 10 Shopping | 3 | 5, 6, 7 |
| 11 Formatting | 4, 8, 10 | 12 |
| 12 Access control | 2 | 11 |
| 13 Consultation handlers | 6, 11, 12 | — |
| 14 Plan-changing handlers | 8, 13 | 15, 17 |
| 15 Catalogue browsing | 5, 13 | 14, 17 |
| 16 Wizards | 15 | 14, 17, 18 |
| 17 Settings handlers | 6, 13 | 14, 15 |
| 18 Scheduler | 14 | 16, 17 |
| 19 Entry point | 16, 17, 18 | — |
| 20 Integration suite and coverage gate | 19 | — |
| 21 Image and pipeline | 20 | — |

Tasks 7 to 10 are pure and depend only on the models, so the solver and the aggregator can be built alongside the repository work in 5 and 6.

## The three testing layers

The plan does not have a testing phase bolted on the end, because tests written after the fact test what the code does rather than what it should do. Instead there are three layers, each catching what the one below cannot:

1. **Unit tests, inside every task.** TDD: the failing test comes first, in the same commit as the code. These pin down each module's contract.
2. **Invariant tests, Task 9.** Generated catalogues and seeds, checked against properties derived from the implementation's own relaxation ladder. These catch the solver bugs nobody thought to write an example for, and the 50-week run answers a question no unit test can: does the cooldown starve a real catalogue over time.
3. **Integration tests, Task 20.** The assembled application, a real SQLite file, real `Update` objects, a fake transport. These catch the wiring: a handler in the wrong group, callback data that does not match its button, a `bot_data` key spelled two ways.

Three architecture guards run as ordinary tests rather than as review habits: `planner.py` may not import `sqlite3`, `telegram` or `datetime.now`; only `repo.py` and `db.py` may execute SQL; and no module but `formatting.py` may contain a non-ASCII literal. Each one fails the build the moment a layer leaks into another.

A natural stopping point for a first usable bot is Task 19: at that point everything works locally against a SQLite file and a real bot token. Tasks 20 and 21 are hardening and packaging.

## Deployment is out of scope for this repository

Nothing about where this bot runs lives here: no orchestrator manifest, no deploy workflow, no host or storage detail, no secret names, no personal detail. This repository builds and publishes a container image and stops there. See `AGENTS.md → Self-contained and anonymous`.

Task 21 is the handover point: once the image is public on the registry, the separate infrastructure repository takes over.
