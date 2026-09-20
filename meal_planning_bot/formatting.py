from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from math import ceil

from meal_planning_bot.models import (
    SLOT_ORDER,
    Category,
    Dish,
    Food,
    MealType,
    Plan,
    PlanEntry,
    Slot,
    Unit,
)
from meal_planning_bot.planner import Diagnosis
from meal_planning_bot.shopping import ShoppingGroup, ShoppingLine

MESSAGE_LIMIT = 4000
DISHES_PAGE_SIZE = 20

DAY_LABELS: tuple[str, ...] = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes")

SLOT_LABELS: dict[Slot, str] = {
    Slot.BREAKFAST: "Desayuno",
    Slot.SNACK1: "Snack 1",
    Slot.LUNCH: "Comida",
    Slot.SNACK2: "Snack 2",
    Slot.DINNER: "Cena",
}

MEAL_TYPE_LABELS: dict[MealType, str] = {
    MealType.BREAKFAST: "Desayuno",
    MealType.SNACK: "Snack",
    MealType.LUNCH: "Comida",
    MealType.DINNER: "Cena",
}

CATEGORY_LABELS: dict[Category, str] = {
    Category.PRODUCE: "Frutas y verduras",
    Category.MEAT_FISH: "Carne y pescado",
    Category.DAIRY_EGGS: "Lácteos y huevos",
    Category.BAKERY: "Panadería",
    Category.FROZEN: "Congelados",
    Category.PANTRY: "Despensa",
    Category.DRINKS: "Bebidas",
    Category.OTHER: "Otros",
}

UNIT_LABELS: dict[Unit, str] = {Unit.G: "g", Unit.ML: "ml", Unit.UNIT: "ud"}

NO_PLAN_MESSAGE = "No hay un plan para esa semana. Usa /regenerate para crearlo."
WEEKEND_MESSAGE = "El fin de semana no está planificado."
SWAP_USAGE_MESSAGE = (
    "Uso: /swap <día> <turno> [siguiente]. "
    "Día: lunes a viernes, o un número del 1 al 5. "
    "Turno: desayuno, snack1, comida, snack2 o cena."
)
PRIVATE_ONLY_MESSAGE = "Ese comando solo funciona en un chat privado conmigo."
DISH_NOT_FOUND_MESSAGE = "No encontré ningún plato con ese nombre."
FOOD_NOT_FOUND_MESSAGE = "No encontré ningún alimento con ese nombre."
RESTORE_NOT_FOUND_MESSAGE = "No encontré nada archivado con ese nombre."
UNKNOWN_ARGUMENT_MESSAGE = "No entendí ese argumento."
SWAP_UNSATISFIABLE_MESSAGE = (
    "No hay ningún plato que encaje en ese turno sin romper las restricciones. "
    "Se mantiene el plato actual."
)
PLANNER_FAILURE_HEADER = "No se pudo generar un plan que cumpla las restricciones:"
KCAL_WINDOW_UNREACHABLE_MESSAGE = (
    "El margen de calorías no es alcanzable con los platos disponibles."
)


# --- plan and day -----------------------------------------------------------


def _entries_for_day(entries: Sequence[PlanEntry], day: int) -> dict[Slot, PlanEntry]:
    return {entry.slot: entry for entry in entries if entry.day == day}


def _day_block(
    day: int, day_date: date, entries: Sequence[PlanEntry], dishes: Mapping[int, Dish]
) -> str:
    by_slot = _entries_for_day(entries, day)
    lines = [f"{DAY_LABELS[day]} {day_date:%d/%m}"]
    total = 0
    for slot in SLOT_ORDER:
        dish = dishes[by_slot[slot].dish_id]
        lines.append(f"  {SLOT_LABELS[slot]}: {dish.name} ({dish.kcal} kcal)")
        total += dish.kcal
    lines.append(f"  Total: {total} kcal")
    return "\n".join(lines)


def render_plan(plan: Plan, dishes: Mapping[int, Dish], is_next_week: bool) -> str:
    heading = "Plan de la semana que viene" if is_next_week else "Plan de esta semana"
    header = f"{heading} (semana del {plan.week_start:%d/%m}):"
    blocks = [
        _day_block(day, plan.week_start + timedelta(days=day), plan.entries, dishes)
        for day in range(5)
    ]
    return "\n\n".join([header, *blocks])


def render_day(plan: Plan, dishes: Mapping[int, Dish], day: int) -> str:
    return _day_block(day, plan.week_start + timedelta(days=day), plan.entries, dishes)


def render_my_id(user_id: int) -> str:
    return f"Tu ID de Telegram es {user_id}."


# --- shopping list -----------------------------------------------------------
#
# render_shopping splits at a category boundary whenever adding the next
# category would push a message past MESSAGE_LIMIT. If a single category is
# itself larger than MESSAGE_LIMIT, it is split line by line instead, since
# there is no smaller natural boundary to split on; each continuation repeats
# the category header suffixed with "(cont.)" so every message is
# self-describing on its own.


def _format_shopping_line(line: ShoppingLine) -> str:
    return f"- {line.food_name}: {line.quantity} {UNIT_LABELS[line.unit]}"


def _category_block(group: ShoppingGroup) -> str:
    lines = [f"{CATEGORY_LABELS[group.category]}:"]
    lines.extend(_format_shopping_line(line) for line in group.lines)
    return "\n".join(lines)


def _split_oversized_block(block: str) -> list[str]:
    header, *body = block.split("\n")
    chunks: list[str] = []
    current = [header]
    current_len = len(header)
    for line in body:
        addition = len(line) + 1
        if current_len + addition > MESSAGE_LIMIT and len(current) > 1:
            chunks.append("\n".join(current))
            current = [f"{header} (cont.)"]
            current_len = len(current[0])
        current.append(line)
        current_len += addition
    chunks.append("\n".join(current))
    return chunks


def render_shopping(groups: Sequence[ShoppingGroup]) -> list[str]:
    messages: list[str] = []
    current: list[str] = []
    current_len = 0
    for group in groups:
        block = _category_block(group)
        addition = len(block) + (2 if current else 0)
        if current and current_len + addition > MESSAGE_LIMIT:
            messages.append("\n\n".join(current))
            current = []
            current_len = 0
            addition = len(block)
        if len(block) > MESSAGE_LIMIT:
            messages.extend(_split_oversized_block(block))
            continue
        current.append(block)
        current_len += addition
    if current:
        messages.append("\n\n".join(current))
    return messages


# --- dishes and foods --------------------------------------------------------


def render_dish(dish: Dish, foods: Mapping[int, Food]) -> str:
    kcal_note = "fijadas manualmente" if dish.kcal_override is not None else "calculadas"
    lines = [
        dish.name,
        MEAL_TYPE_LABELS[dish.meal_type],
        f"{dish.kcal} kcal ({kcal_note})",
        "Ingredientes:",
    ]
    for ingredient in dish.ingredients:
        food = foods[ingredient.food_id]
        lines.append(f"- {food.name}: {ingredient.quantity:g} {UNIT_LABELS[food.unit]}")
    if dish.steps:
        lines.append("Preparación:")
        lines.append(dish.steps)
    return "\n".join(lines)


def render_dishes_page(dishes: Sequence[Dish], page: int) -> str:
    total_pages = max(1, ceil(len(dishes) / DISHES_PAGE_SIZE))
    start = (page - 1) * DISHES_PAGE_SIZE
    page_dishes = dishes[start : start + DISHES_PAGE_SIZE]
    lines = [f"Página {page} de {total_pages}"]
    current_meal_type: MealType | None = None
    for dish in page_dishes:
        if dish.meal_type is not current_meal_type:
            current_meal_type = dish.meal_type
            lines.append(f"{MEAL_TYPE_LABELS[dish.meal_type]}:")
        lines.append(f"- {dish.name} ({dish.kcal} kcal)")
    return "\n".join(lines)


def render_foods_page(foods: Sequence[Food], page: int) -> str:
    total_pages = max(1, ceil(len(foods) / DISHES_PAGE_SIZE))
    start = (page - 1) * DISHES_PAGE_SIZE
    page_foods = foods[start : start + DISHES_PAGE_SIZE]
    lines = [f"Página {page} de {total_pages}"]
    current_category: Category | None = None
    for food in page_foods:
        if food.category is not current_category:
            current_category = food.category
            lines.append(f"{CATEGORY_LABELS[food.category]}:")
        lines.append(
            f"- {food.name}: {UNIT_LABELS[food.unit]}, {food.kcal_ref:g} kcal de referencia"
        )
    return "\n".join(lines)


DISH_FUZZY_PROMPT = "Varios platos coinciden:"
RESTORE_AMBIGUOUS_PROMPT = "Varios archivados coinciden:"
PAGINATION_PREV_BUTTON = "< Anterior"
PAGINATION_NEXT_BUTTON = "Siguiente >"


def render_restored_dish(dish: Dish) -> str:
    return f"Plato restaurado: {dish.name}."


def render_restored_food(food: Food) -> str:
    return f"Alimento restaurado: {food.name}."


# --- relaxation ---------------------------------------------------------------

RELAXATION_MESSAGES: dict[int, str] = {
    1: "se redujeron a la mitad los días de espera entre repeticiones",
    2: "los días de espera entre repeticiones se fijaron en un día",
    3: "se permitió un alimento repetido más al día",
    4: "se duplicó el margen de calorías permitido",
}


def render_relaxation_notice(step: int) -> str:
    if step <= 0:
        return ""
    return f"Para poder generar el plan, {RELAXATION_MESSAGES[step]}."


def render_swap_unsatisfiable() -> str:
    return SWAP_UNSATISFIABLE_MESSAGE


def render_planner_failure(diagnosis: Diagnosis) -> str:
    lines = [PLANNER_FAILURE_HEADER]
    for shortfall in diagnosis.shortfalls:
        lines.append(
            f"- {MEAL_TYPE_LABELS[shortfall.meal_type]}: hay {shortfall.active} "
            f"plato(s) activo(s), se necesitan {shortfall.required}."
        )
    if not diagnosis.kcal_window_reachable:
        lines.append(KCAL_WINDOW_UNREACHABLE_MESSAGE)
    return "\n".join(lines)


# --- help ---------------------------------------------------------------------


class CommandGroup(StrEnum):
    CONSULTATION = "consultation"
    PLAN = "plan"
    CATALOGUE = "catalogue"
    CONFIGURATION = "configuration"


GROUP_LABELS: dict[CommandGroup, str] = {
    CommandGroup.CONSULTATION: "Consulta",
    CommandGroup.PLAN: "Planificación",
    CommandGroup.CATALOGUE: "Catálogo",
    CommandGroup.CONFIGURATION: "Configuración",
}

GROUP_ORDER: tuple[CommandGroup, ...] = (
    CommandGroup.CONSULTATION,
    CommandGroup.PLAN,
    CommandGroup.CATALOGUE,
    CommandGroup.CONFIGURATION,
)


@dataclass(frozen=True)
class CommandInfo:
    name: str
    usage: str
    description: str
    group: CommandGroup


COMMANDS: tuple[CommandInfo, ...] = (
    CommandInfo("start", "/start", "Muestra la lista de comandos", CommandGroup.CONSULTATION),
    CommandInfo("help", "/help", "Muestra la lista de comandos", CommandGroup.CONSULTATION),
    CommandInfo("myid", "/myid", "Devuelve tu ID de Telegram", CommandGroup.CONSULTATION),
    CommandInfo(
        "plan",
        "/plan [siguiente]",
        "Plan de esta semana; añade 'siguiente' para ver la semana que viene",
        CommandGroup.PLAN,
    ),
    CommandInfo("today", "/today", "Los cinco turnos de hoy", CommandGroup.PLAN),
    CommandInfo(
        "shopping",
        "/shopping [siguiente]",
        "Lista de la compra de esa semana",
        CommandGroup.PLAN,
    ),
    CommandInfo(
        "regenerate",
        "/regenerate [siguiente]",
        "Vuelve a sortear el plan de esa semana",
        CommandGroup.PLAN,
    ),
    CommandInfo(
        "swap",
        "/swap <día> <turno> [siguiente]",
        "Vuelve a sortear un solo turno",
        CommandGroup.PLAN,
    ),
    CommandInfo(
        "dishes",
        "/dishes [archivados]",
        "Explora los platos activos o archivados",
        CommandGroup.CATALOGUE,
    ),
    CommandInfo(
        "dish", "/dish <nombre>", "Ficha completa de un plato", CommandGroup.CATALOGUE
    ),
    CommandInfo(
        "foods",
        "/foods [archivados]",
        "Explora los alimentos activos o archivados",
        CommandGroup.CATALOGUE,
    ),
    CommandInfo(
        "restore",
        "/restore <nombre>",
        "Reactiva un plato o alimento archivado",
        CommandGroup.CATALOGUE,
    ),
    CommandInfo(
        "newdish", "/newdish", "Asistente para crear un plato", CommandGroup.CATALOGUE
    ),
    CommandInfo(
        "editdish", "/editdish", "Asistente para editar un plato", CommandGroup.CATALOGUE
    ),
    CommandInfo("deletedish", "/deletedish", "Archiva un plato", CommandGroup.CATALOGUE),
    CommandInfo(
        "newfood", "/newfood", "Asistente para crear un alimento", CommandGroup.CATALOGUE
    ),
    CommandInfo(
        "editfood", "/editfood", "Asistente para editar un alimento", CommandGroup.CATALOGUE
    ),
    CommandInfo("deletefood", "/deletefood", "Archiva un alimento", CommandGroup.CATALOGUE),
    CommandInfo(
        "cancel", "/cancel", "Cancela el asistente en curso", CommandGroup.CATALOGUE
    ),
    CommandInfo(
        "settings",
        "/settings",
        "Muestra cada ajuste y su valor",
        CommandGroup.CONFIGURATION,
    ),
    CommandInfo(
        "set",
        "/set <clave> <valor>",
        "Cambia un ajuste",
        CommandGroup.CONFIGURATION,
    ),
)


def render_help() -> str:
    lines: list[str] = []
    for group in GROUP_ORDER:
        commands = [c for c in COMMANDS if c.group is group]
        if not commands:
            continue
        lines.append(f"{GROUP_LABELS[group]}:")
        for command in commands:
            lines.append(f"{command.usage} - {command.description}")
    return "\n".join(lines)


# --- wizards -------------------------------------------------------------

WIZARD_REPLACED_NOTICE = "Se canceló el asistente anterior para empezar este."
WIZARD_CANCELLED_MESSAGE = "Asistente cancelado. No se guardó nada."
NO_WIZARD_IN_PROGRESS_MESSAGE = "No hay ningún asistente en curso."

NEWDISH_NAME_PROMPT = "¿Cómo se llama el plato?"
MEAL_TYPE_PROMPT = "¿Qué tipo de comida es?"
INGREDIENT_PROMPT = (
    "Indica un ingrediente y su cantidad, por ejemplo: «pollo 200». "
    "Cuando termines, pulsa Terminar."
)
INGREDIENT_ADDED_PROMPT = (
    "Añadido. Indica otro ingrediente, o pulsa Terminar si ya no faltan más."
)
INGREDIENT_FORMAT_ERROR_MESSAGE = (
    "No entendí eso. Escribe el nombre del alimento seguido de la cantidad, "
    "por ejemplo: «pollo 200»."
)
INGREDIENT_QUANTITY_ERROR_MESSAGE = "La cantidad debe ser un número positivo."
INGREDIENT_NEEDS_ONE_MESSAGE = "Añade al menos un ingrediente antes de terminar."
INGREDIENT_DONE_BUTTON = "Terminar"
FOOD_AMBIGUOUS_PROMPT = "Varios alimentos coinciden, elige uno:"

STEPS_PROMPT = "Describe la preparación, o pulsa Saltar."
STEPS_SKIP_BUTTON = "Saltar"

KCAL_ACCEPT_BUTTON = "Aceptar"
KCAL_INVALID_MESSAGE = "Las calorías deben ser un número entero positivo."

CONFIRM_BUTTON = "Confirmar"
DISCARD_BUTTON = "Descartar"
CONFIRM_HEADER = "Revisa antes de guardar:"

DISH_NAME_DUPLICATE_MESSAGE = "Ya existe un plato o alimento con ese nombre."
DISH_DISCARDED_MESSAGE = "Se descartó el plato. No se guardó nada."
FOOD_DISCARDED_MESSAGE = "Se descartó el alimento. No se guardó nada."

EDIT_DISH_RESOLVE_PROMPT = "¿Qué plato quieres editar?"
EDIT_FOOD_RESOLVE_PROMPT = "¿Qué alimento quieres editar?"
DELETE_DISH_RESOLVE_PROMPT = "¿Qué plato quieres archivar?"
DELETE_FOOD_RESOLVE_PROMPT = "¿Qué alimento quieres archivar?"
EDIT_FIELD_PROMPT = "¿Qué quieres cambiar?"

DISH_FIELD_LABELS: dict[str, str] = {
    "name": "Nombre",
    "meal_type": "Tipo de comida",
    "ingredients": "Ingredientes",
    "steps": "Preparación",
    "kcal": "Calorías",
}

FOOD_FIELD_LABELS: dict[str, str] = {
    "name": "Nombre",
    "unit": "Unidad",
    "category": "Categoría",
    "kcal_ref": "Calorías de referencia",
}

NEWFOOD_NAME_PROMPT = "¿Cómo se llama el alimento?"
FOOD_UNIT_PROMPT = "¿Qué unidad usa?"
FOOD_CATEGORY_PROMPT = "¿Qué categoría tiene?"
FOOD_KCAL_PROMPT = "¿Cuántas kcal de referencia tiene?"
FOOD_KCAL_INVALID_MESSAGE = "Las kcal de referencia deben ser un número no negativo."


def render_new_food_unit_prompt(seed_unit: Unit | None) -> str:
    if seed_unit is None:
        return FOOD_UNIT_PROMPT
    return f"{FOOD_UNIT_PROMPT} (sugerido: {UNIT_LABELS[seed_unit]})"


def render_new_food_category_prompt(seed_category: Category | None) -> str:
    if seed_category is None:
        return FOOD_CATEGORY_PROMPT
    return f"{FOOD_CATEGORY_PROMPT} (sugerido: {CATEGORY_LABELS[seed_category]})"


def render_new_food_kcal_prompt(seed_kcal_ref: float | None) -> str:
    if seed_kcal_ref is None:
        return FOOD_KCAL_PROMPT
    return f"{FOOD_KCAL_PROMPT} (sugerido: {seed_kcal_ref:g})"


def render_kcal_step_prompt(computed: int) -> str:
    return f"Calorías calculadas: {computed} kcal. Pulsa Aceptar o escribe un valor distinto."


def render_dish_created(name: str) -> str:
    return f"Plato creado: {name}."


def render_dish_updated(name: str) -> str:
    return f"Plato actualizado: {name}."


def render_food_created(name: str) -> str:
    return f"Alimento creado: {name}."


def render_food_updated(name: str) -> str:
    return f"Alimento actualizado: {name}."


def render_delete_dish_confirm(dish: Dish) -> str:
    return f"¿Archivar el plato «{dish.name}»? Ya no se sorteará en nuevos planes."


def render_delete_dish_done(name: str) -> str:
    return f"Plato archivado: {name}. Usa /restore para recuperarlo."


def render_delete_food_confirm(food: Food) -> str:
    return f"¿Archivar el alimento «{food.name}»? Ya no se podrá usar en nuevos platos."


def render_delete_food_done(name: str) -> str:
    return f"Alimento archivado: {name}. Usa /restore para recuperarlo."


def render_food_in_use(dish_names: Sequence[str]) -> str:
    joined = ", ".join(dish_names)
    return f"No se puede archivar: lo usan estos platos: {joined}."


def render_food_summary(food: Food) -> str:
    return (
        f"{food.name}\n"
        f"{CATEGORY_LABELS[food.category]}\n"
        f"{UNIT_LABELS[food.unit]}, {food.kcal_ref:g} kcal de referencia"
    )


YES_BUTTON = "Sí"
NO_BUTTON = "No"
DELETE_CANCELLED_MESSAGE = "No se archivó nada."
KCAL_REF_ACCEPT_SEED_BUTTON = "Usar sugerido"


# --- settings --------------------------------------------------------------

SET_USAGE_MESSAGE = "Uso: /set <clave> <valor>."


def render_settings(rows: Sequence[tuple[str, str, str]]) -> str:
    lines = ["Ajustes:"]
    for key, value, default in rows:
        lines.append(f"{key}: {value} (por defecto: {default})")
    return "\n".join(lines)


def render_unknown_setting_key(valid_keys: Sequence[str]) -> str:
    joined = ", ".join(valid_keys)
    return f"Esa clave no existe. Claves válidas: {joined}."


def render_setting_out_of_range(key: str, low: int, high: int) -> str:
    return f"{key} debe estar entre {low} y {high}."


def render_setting_bad_time(key: str) -> str:
    return f"{key} debe tener formato HH:MM, por ejemplo 18:00."


def render_setting_changed(key: str, old: str, new: str) -> str:
    return f"{key}: {old} -> {new}."
