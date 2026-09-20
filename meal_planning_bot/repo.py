import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from meal_planning_bot.models import (
    SLOT_ORDER,
    Category,
    Dish,
    DishIngredient,
    Food,
    MealType,
    Plan,
    PlanEntry,
    PlannerSettings,
    ServedRecord,
    Slot,
    Unit,
)
from meal_planning_bot.nutrition import effective_kcal
from meal_planning_bot.weeks import current_week_start, next_week_start


class RepoError(Exception):
    pass


class FoodInUse(RepoError):
    def __init__(self, dish_names: list[str]) -> None:
        self.dish_names = dish_names
        super().__init__(f"food is used by: {', '.join(dish_names)}")


class SettingError(RepoError):
    pass


# --- foods ---------------------------------------------------------------


def _food_from_row(row: sqlite3.Row) -> Food:
    return Food(
        id=row["id"],
        name=row["name"],
        unit=Unit(row["unit"]),
        category=Category(row["category"]),
        kcal_ref=row["kcal_ref"],
        active=bool(row["active"]),
    )


def _food_row(conn: sqlite3.Connection, food_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"food {food_id} not found")
    return row


def create_food(
    conn: sqlite3.Connection, *, name: str, unit: Unit, category: Category, kcal_ref: float
) -> Food:
    with conn:
        try:
            cur = conn.execute(
                "INSERT INTO foods (name, unit, category, kcal_ref) VALUES (?, ?, ?, ?)",
                (name, unit.value, category.value, kcal_ref),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"food name already exists: {name}") from exc
    return _food_from_row(_food_row(conn, cur.lastrowid))  # type: ignore[arg-type]


def update_food(
    conn: sqlite3.Connection,
    food_id: int,
    *,
    name: str | None = None,
    unit: Unit | None = None,
    category: Category | None = None,
    kcal_ref: float | None = None,
) -> Food:
    current = _food_from_row(_food_row(conn, food_id))
    if unit is not None and unit != current.unit and kcal_ref is None:
        raise ValueError("changing a food's unit requires a new kcal_ref")

    new_name = name if name is not None else current.name
    new_unit = unit if unit is not None else current.unit
    new_category = category if category is not None else current.category
    new_kcal_ref = kcal_ref if kcal_ref is not None else current.kcal_ref

    with conn:
        try:
            conn.execute(
                "UPDATE foods SET name = ?, unit = ?, category = ?, kcal_ref = ? WHERE id = ?",
                (new_name, new_unit.value, new_category.value, new_kcal_ref, food_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"food name already exists: {new_name}") from exc
    return _food_from_row(_food_row(conn, food_id))


def deactivate_food(conn: sqlite3.Connection, food_id: int) -> None:
    rows = conn.execute(
        "SELECT DISTINCT d.name FROM dishes d "
        "JOIN dish_ingredients di ON di.dish_id = d.id "
        "WHERE di.food_id = ? ORDER BY d.name",
        (food_id,),
    ).fetchall()
    if rows:
        raise FoodInUse([row["name"] for row in rows])
    with conn:
        conn.execute("UPDATE foods SET active = 0 WHERE id = ?", (food_id,))


def reactivate_food(conn: sqlite3.Connection, food_id: int) -> Food:
    with conn:
        conn.execute("UPDATE foods SET active = 1 WHERE id = ?", (food_id,))
    return _food_from_row(_food_row(conn, food_id))


def find_foods_by_name(conn: sqlite3.Connection, text: str, limit: int = 5) -> list[Food]:
    rows = conn.execute(
        "SELECT * FROM foods WHERE active = 1 AND lower(name) LIKE ? ORDER BY name LIMIT ?",
        (f"%{text.strip().lower()}%", limit),
    ).fetchall()
    return [_food_from_row(row) for row in rows]


def get_food_by_exact_name(conn: sqlite3.Connection, name: str) -> Food | None:
    row = conn.execute(
        "SELECT * FROM foods WHERE lower(name) = ?", (name.strip().lower(),)
    ).fetchone()
    return _food_from_row(row) if row is not None else None


def list_foods(conn: sqlite3.Connection, *, archived: bool = False) -> list[Food]:
    rows = conn.execute(
        "SELECT * FROM foods WHERE active = ? ORDER BY name", (0 if archived else 1,)
    ).fetchall()
    return [_food_from_row(row) for row in rows]


def get_food(conn: sqlite3.Connection, food_id: int) -> Food:
    return _food_from_row(_food_row(conn, food_id))


# --- dishes ----------------------------------------------------------------


class _Unset:
    pass


_UNSET = _Unset()


def _load_foods(conn: sqlite3.Connection, food_ids: set[int]) -> dict[int, Food]:
    if not food_ids:
        return {}
    placeholders = ", ".join("?" for _ in food_ids)
    rows = conn.execute(
        f"SELECT * FROM foods WHERE id IN ({placeholders})", tuple(food_ids)
    ).fetchall()
    return {row["id"]: _food_from_row(row) for row in rows}


def _dish_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Dish:
    ingredient_rows = conn.execute(
        "SELECT food_id, quantity FROM dish_ingredients WHERE dish_id = ? ORDER BY food_id",
        (row["id"],),
    ).fetchall()
    ingredients = tuple(
        DishIngredient(food_id=r["food_id"], quantity=r["quantity"]) for r in ingredient_rows
    )
    foods = _load_foods(conn, {i.food_id for i in ingredients})
    kcal = effective_kcal(ingredients, foods, row["kcal_override"])
    return Dish(
        id=row["id"],
        name=row["name"],
        meal_type=MealType(row["meal_type"]),
        kcal=kcal,
        ingredients=ingredients,
        kcal_override=row["kcal_override"],
        steps=row["steps"],
        active=bool(row["active"]),
    )


def _dish_row(conn: sqlite3.Connection, dish_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM dishes WHERE id = ?", (dish_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"dish {dish_id} not found")
    return row


def _validate_ingredients(ingredients: Sequence[DishIngredient]) -> None:
    if not ingredients:
        raise ValueError("a dish must have at least one ingredient")
    food_ids = [i.food_id for i in ingredients]
    if len(set(food_ids)) != len(food_ids):
        raise ValueError("a dish cannot list the same food twice")


def create_dish(
    conn: sqlite3.Connection,
    *,
    name: str,
    meal_type: MealType,
    ingredients: Sequence[DishIngredient],
    kcal_override: int | None = None,
    steps: str | None = None,
) -> Dish:
    _validate_ingredients(ingredients)
    with conn:
        try:
            cur = conn.execute(
                "INSERT INTO dishes (name, meal_type, kcal_override, steps) VALUES (?, ?, ?, ?)",
                (name, meal_type.value, kcal_override, steps),
            )
            dish_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO dish_ingredients (dish_id, food_id, quantity) VALUES (?, ?, ?)",
                [(dish_id, i.food_id, i.quantity) for i in ingredients],
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"could not create dish {name!r}: {exc}") from exc
    return _dish_from_row(conn, _dish_row(conn, dish_id))  # type: ignore[arg-type]


def update_dish(
    conn: sqlite3.Connection,
    dish_id: int,
    *,
    name: str | None = None,
    meal_type: MealType | None = None,
    ingredients: Sequence[DishIngredient] | None = None,
    kcal_override: int | None | _Unset = _UNSET,
    steps: str | None | _Unset = _UNSET,
) -> Dish:
    current = _dish_from_row(conn, _dish_row(conn, dish_id))

    new_name = name if name is not None else current.name
    new_meal_type = meal_type if meal_type is not None else current.meal_type
    new_ingredients = ingredients if ingredients is not None else current.ingredients
    new_kcal_override = (
        current.kcal_override if isinstance(kcal_override, _Unset) else kcal_override
    )
    new_steps = current.steps if isinstance(steps, _Unset) else steps

    _validate_ingredients(new_ingredients)

    with conn:
        try:
            conn.execute(
                "UPDATE dishes SET name = ?, meal_type = ?, kcal_override = ?, steps = ? "
                "WHERE id = ?",
                (new_name, new_meal_type.value, new_kcal_override, new_steps, dish_id),
            )
            if ingredients is not None:
                conn.execute("DELETE FROM dish_ingredients WHERE dish_id = ?", (dish_id,))
                conn.executemany(
                    "INSERT INTO dish_ingredients (dish_id, food_id, quantity) VALUES (?, ?, ?)",
                    [(dish_id, i.food_id, i.quantity) for i in new_ingredients],
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"could not update dish {dish_id}: {exc}") from exc
    return _dish_from_row(conn, _dish_row(conn, dish_id))


@dataclass(frozen=True)
class NewFoodSpec:
    name: str
    unit: Unit
    category: Category
    kcal_ref: float


# An ingredient reference during a wizard confirmation: either an existing
# food's id, or (None, name) pointing at one of the NewFoodSpec entries
# created in the same call, resolved to a real id only after that insert.
IngredientRef = tuple[int | None, str | None, float]


def _insert_new_foods(conn: sqlite3.Connection, new_foods: Sequence[NewFoodSpec]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for spec in new_foods:
        cur = conn.execute(
            "INSERT INTO foods (name, unit, category, kcal_ref) VALUES (?, ?, ?, ?)",
            (spec.name, spec.unit.value, spec.category.value, spec.kcal_ref),
        )
        ids[spec.name.lower()] = cur.lastrowid  # type: ignore[assignment]
    return ids


def _resolve_ingredient_refs(
    ingredients: Sequence[IngredientRef], new_food_ids: Mapping[str, int]
) -> list[DishIngredient]:
    resolved = []
    for food_id, food_name, quantity in ingredients:
        if food_id is not None:
            resolved.append(DishIngredient(food_id=food_id, quantity=quantity))
        else:
            assert food_name is not None
            resolved.append(
                DishIngredient(food_id=new_food_ids[food_name.lower()], quantity=quantity)
            )
    return resolved


def create_dish_with_new_foods(
    conn: sqlite3.Connection,
    *,
    name: str,
    meal_type: MealType,
    new_foods: Sequence[NewFoodSpec],
    ingredients: Sequence[IngredientRef],
    kcal_override: int | None = None,
    steps: str | None = None,
) -> Dish:
    # A wizard confirmation may need to create foods inline before the dish
    # that references them; both writes must succeed or fail together, so
    # this uses one `with conn:` block instead of composing create_food and
    # create_dish, each of which commits (and so cannot be rolled back) on
    # its own.
    with conn:
        try:
            new_food_ids = _insert_new_foods(conn, new_foods)
            resolved = _resolve_ingredient_refs(ingredients, new_food_ids)
            _validate_ingredients(resolved)
            cur = conn.execute(
                "INSERT INTO dishes (name, meal_type, kcal_override, steps) VALUES (?, ?, ?, ?)",
                (name, meal_type.value, kcal_override, steps),
            )
            dish_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO dish_ingredients (dish_id, food_id, quantity) VALUES (?, ?, ?)",
                [(dish_id, i.food_id, i.quantity) for i in resolved],
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"could not create dish {name!r}: {exc}") from exc
    return _dish_from_row(conn, _dish_row(conn, dish_id))  # type: ignore[arg-type]


def update_dish_ingredients_with_new_foods(
    conn: sqlite3.Connection,
    dish_id: int,
    *,
    new_foods: Sequence[NewFoodSpec],
    ingredients: Sequence[IngredientRef],
) -> Dish:
    with conn:
        try:
            new_food_ids = _insert_new_foods(conn, new_foods)
            resolved = _resolve_ingredient_refs(ingredients, new_food_ids)
            _validate_ingredients(resolved)
            conn.execute("DELETE FROM dish_ingredients WHERE dish_id = ?", (dish_id,))
            conn.executemany(
                "INSERT INTO dish_ingredients (dish_id, food_id, quantity) VALUES (?, ?, ?)",
                [(dish_id, i.food_id, i.quantity) for i in resolved],
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"could not update dish {dish_id}: {exc}") from exc
    return _dish_from_row(conn, _dish_row(conn, dish_id))


def deactivate_dish(
    conn: sqlite3.Connection, dish_id: int, today: date
) -> list[tuple[date, int, Slot]]:
    weeks_to_check = (current_week_start(today), next_week_start(today))
    affected: list[tuple[date, int, Slot]] = []
    with conn:
        conn.execute("UPDATE dishes SET active = 0 WHERE id = ?", (dish_id,))
        for week_start in weeks_to_check:
            plan_row = conn.execute(
                "SELECT id FROM plans WHERE week_start = ?", (week_start.isoformat(),)
            ).fetchone()
            if plan_row is None:
                continue
            entry_rows = conn.execute(
                "SELECT day, slot FROM plan_entries WHERE plan_id = ? AND dish_id = ?",
                (plan_row["id"], dish_id),
            ).fetchall()
            affected.extend((week_start, r["day"], Slot(r["slot"])) for r in entry_rows)
    return affected


def reactivate_dish(conn: sqlite3.Connection, dish_id: int) -> Dish:
    with conn:
        conn.execute("UPDATE dishes SET active = 1 WHERE id = ?", (dish_id,))
    return _dish_from_row(conn, _dish_row(conn, dish_id))


def get_dish(conn: sqlite3.Connection, dish_id: int) -> Dish:
    return _dish_from_row(conn, _dish_row(conn, dish_id))


def find_dishes_by_name(conn: sqlite3.Connection, text: str, limit: int = 5) -> list[Dish]:
    rows = conn.execute(
        "SELECT * FROM dishes WHERE active = 1 AND lower(name) LIKE ? ORDER BY name LIMIT ?",
        (f"%{text.strip().lower()}%", limit),
    ).fetchall()
    return [_dish_from_row(conn, row) for row in rows]


def list_dishes(conn: sqlite3.Connection, *, archived: bool = False) -> list[Dish]:
    rows = conn.execute(
        "SELECT * FROM dishes WHERE active = ? ORDER BY name", (0 if archived else 1,)
    ).fetchall()
    return [_dish_from_row(conn, row) for row in rows]


def count_dishes_by_meal_type(conn: sqlite3.Connection) -> dict[MealType, int]:
    counts: dict[MealType, int] = dict.fromkeys(MealType, 0)
    rows = conn.execute(
        "SELECT meal_type, count(*) AS n FROM dishes WHERE active = 1 GROUP BY meal_type"
    ).fetchall()
    for row in rows:
        counts[MealType(row["meal_type"])] = row["n"]
    return counts


# --- plans and history -------------------------------------------------


def save_plan(conn: sqlite3.Connection, plan: Plan) -> None:
    generated_at = datetime.now(UTC).isoformat()
    week_start_iso = plan.week_start.isoformat()
    with conn:
        conn.execute(
            "INSERT INTO plans (week_start, generated_at, relaxation) VALUES (?, ?, ?) "
            "ON CONFLICT(week_start) DO UPDATE SET "
            "generated_at = excluded.generated_at, relaxation = excluded.relaxation",
            (week_start_iso, generated_at, plan.relaxation),
        )
        plan_id = conn.execute(
            "SELECT id FROM plans WHERE week_start = ?", (week_start_iso,)
        ).fetchone()["id"]
        conn.execute("DELETE FROM plan_entries WHERE plan_id = ?", (plan_id,))
        conn.executemany(
            "INSERT INTO plan_entries (plan_id, day, slot, dish_id) VALUES (?, ?, ?, ?)",
            [(plan_id, e.day, e.slot.value, e.dish_id) for e in plan.entries],
        )


def get_plan(conn: sqlite3.Connection, week_start: date) -> Plan | None:
    plan_row = conn.execute(
        "SELECT id, relaxation FROM plans WHERE week_start = ?", (week_start.isoformat(),)
    ).fetchone()
    if plan_row is None:
        return None
    entry_rows = conn.execute(
        "SELECT day, slot, dish_id FROM plan_entries WHERE plan_id = ?",
        (plan_row["id"],),
    ).fetchall()
    # Ordered in Python, not SQL: ORDER BY slot sorts the column alphabetically, which
    # interleaves the day as breakfast, dinner, lunch, snack1, snack2. Saving a plan and
    # reading it back would then not round-trip, and any caller iterating entries would
    # get the meals out of sequence.
    entries = tuple(
        sorted(
            (
                PlanEntry(day=r["day"], slot=Slot(r["slot"]), dish_id=r["dish_id"])
                for r in entry_rows
            ),
            key=lambda e: (e.day, SLOT_ORDER.index(e.slot)),
        )
    )
    return Plan(week_start=week_start, entries=entries, relaxation=plan_row["relaxation"])


def scheduled_history(conn: sqlite3.Connection, around: date, days: int = 60) -> list[ServedRecord]:
    lower = around - timedelta(days=days)
    upper = around + timedelta(days=days)
    rows = conn.execute(
        "SELECT p.week_start AS week_start, pe.day AS day, pe.dish_id AS dish_id "
        "FROM plans p JOIN plan_entries pe ON pe.plan_id = p.id"
    ).fetchall()
    records: list[ServedRecord] = []
    for row in rows:
        served_on = date.fromisoformat(row["week_start"]) + timedelta(days=row["day"])
        if lower <= served_on <= upper:
            records.append(ServedRecord(dish_id=row["dish_id"], served_on=served_on))
    return records


# --- settings ------------------------------------------------------------


@dataclass(frozen=True)
class IntSpec:
    default: int
    low: int
    high: int


@dataclass(frozen=True)
class TimeSpec:
    default: str


SettingSpec = IntSpec | TimeSpec

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


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    if key not in SETTING_SPECS:
        raise SettingError(f"unknown setting: {key}")
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise SettingError(f"unknown setting: {key}")
    return str(row["value"])


def _validate_setting(key: str, raw: str) -> str:
    spec = SETTING_SPECS.get(key)
    if spec is None:
        raise SettingError(f"unknown setting: {key}")
    if isinstance(spec, IntSpec):
        try:
            value = int(raw)
        except ValueError as exc:
            raise SettingError(f"{key} must be an integer") from exc
        if not (spec.low <= value <= spec.high):
            raise SettingError(f"{key} must be between {spec.low} and {spec.high}")
        return str(value)

    parts = raw.split(":")
    if len(parts) != 2:
        raise SettingError(f"{key} must be in HH:MM format")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise SettingError(f"{key} must be in HH:MM format") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SettingError(f"{key} must be a valid time in HH:MM format")
    return f"{hour:02d}:{minute:02d}"


def set_setting(conn: sqlite3.Connection, key: str, raw: str) -> tuple[str, str]:
    new_value = _validate_setting(key, raw)
    old_value = get_setting(conn, key)
    with conn:
        conn.execute("UPDATE settings SET value = ? WHERE key = ?", (new_value, key))
    return old_value, new_value


def all_settings(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [(key, get_setting(conn, key), str(spec.default)) for key, spec in SETTING_SPECS.items()]


def planner_settings(conn: sqlite3.Connection) -> PlannerSettings:
    return PlannerSettings(
        daily_kcal_target=int(get_setting(conn, "daily_kcal_target")),
        kcal_tolerance_pct=int(get_setting(conn, "kcal_tolerance_pct")),
        max_food_repeats_per_day=int(get_setting(conn, "max_food_repeats_per_day")),
        cooldown_days={
            MealType.BREAKFAST: int(get_setting(conn, "cooldown_days_breakfast")),
            MealType.SNACK: int(get_setting(conn, "cooldown_days_snack")),
            MealType.LUNCH: int(get_setting(conn, "cooldown_days_lunch")),
            MealType.DINNER: int(get_setting(conn, "cooldown_days_dinner")),
        },
    )
