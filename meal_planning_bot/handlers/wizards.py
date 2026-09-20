from collections.abc import MutableMapping
from dataclasses import dataclass, field
from enum import StrEnum
from sqlite3 import Connection
from typing import Protocol

from meal_planning_bot import nutrition, repo
from meal_planning_bot.access import private_only
from meal_planning_bot.formatting import (
    CATEGORY_LABELS,
    CONFIRM_BUTTON,
    CONFIRM_HEADER,
    DELETE_CANCELLED_MESSAGE,
    DELETE_DISH_RESOLVE_PROMPT,
    DELETE_FOOD_RESOLVE_PROMPT,
    DISCARD_BUTTON,
    DISH_DISCARDED_MESSAGE,
    DISH_FIELD_LABELS,
    DISH_FUZZY_PROMPT,
    DISH_NAME_DUPLICATE_MESSAGE,
    DISH_NOT_FOUND_MESSAGE,
    EDIT_DISH_RESOLVE_PROMPT,
    EDIT_FIELD_PROMPT,
    EDIT_FOOD_RESOLVE_PROMPT,
    FOOD_AMBIGUOUS_PROMPT,
    FOOD_CATEGORY_PROMPT,
    FOOD_DISCARDED_MESSAGE,
    FOOD_FIELD_LABELS,
    FOOD_KCAL_INVALID_MESSAGE,
    FOOD_KCAL_PROMPT,
    FOOD_NOT_FOUND_MESSAGE,
    FOOD_UNIT_PROMPT,
    INGREDIENT_ADDED_PROMPT,
    INGREDIENT_DONE_BUTTON,
    INGREDIENT_FORMAT_ERROR_MESSAGE,
    INGREDIENT_NEEDS_ONE_MESSAGE,
    INGREDIENT_PROMPT,
    INGREDIENT_QUANTITY_ERROR_MESSAGE,
    KCAL_ACCEPT_BUTTON,
    KCAL_INVALID_MESSAGE,
    KCAL_REF_ACCEPT_SEED_BUTTON,
    MEAL_TYPE_LABELS,
    MEAL_TYPE_PROMPT,
    NEWDISH_NAME_PROMPT,
    NEWFOOD_NAME_PROMPT,
    NO_BUTTON,
    NO_WIZARD_IN_PROGRESS_MESSAGE,
    STEPS_PROMPT,
    STEPS_SKIP_BUTTON,
    UNIT_LABELS,
    WIZARD_CANCELLED_MESSAGE,
    WIZARD_REPLACED_NOTICE,
    YES_BUTTON,
    render_delete_dish_confirm,
    render_delete_dish_done,
    render_delete_food_confirm,
    render_delete_food_done,
    render_dish,
    render_dish_created,
    render_dish_updated,
    render_food_created,
    render_food_in_use,
    render_food_summary,
    render_food_updated,
    render_kcal_step_prompt,
    render_new_food_category_prompt,
    render_new_food_kcal_prompt,
    render_new_food_unit_prompt,
)
from meal_planning_bot.handlers import (
    ButtonRow,
    CallbackUpdateLike,
    ContextLike,
    Keyboard,
    UpdateLike,
    get_clock,
    get_conn,
)
from meal_planning_bot.models import (
    CATEGORY_ORDER,
    Category,
    Dish,
    DishIngredient,
    Food,
    MealType,
    Unit,
)
from meal_planning_bot.nutrition import computed_kcal, effective_kcal


class WizardContextLike(ContextLike, Protocol):
    user_data: MutableMapping[str, object]


class WizardKind(StrEnum):
    NEW_DISH = "new_dish"
    EDIT_DISH = "edit_dish"
    DELETE_DISH = "delete_dish"
    NEW_FOOD = "new_food"
    EDIT_FOOD = "edit_food"
    DELETE_FOOD = "delete_food"


class Step(StrEnum):
    NAME = "name"
    MEAL_TYPE = "meal_type"
    INGREDIENT = "ingredient"
    FOOD_UNIT = "food_unit"
    FOOD_CATEGORY = "food_category"
    FOOD_KCAL_REF = "food_kcal_ref"
    STEPS = "steps"
    KCAL = "kcal"
    CONFIRM = "confirm"
    RESOLVE = "resolve"
    FIELD = "field"
    DELETE_CONFIRM = "delete_confirm"


@dataclass
class IngredientDraft:
    food_id: int | None
    food_name: str
    quantity: float


@dataclass
class NewFoodDraft:
    name: str
    unit: Unit
    category: Category
    kcal_ref: float


@dataclass
class WizardState:
    kind: WizardKind
    step: Step
    dish_id: int | None = None
    food_id: int | None = None
    name: str | None = None
    meal_type: MealType | None = None
    ingredients: list[IngredientDraft] = field(default_factory=list)
    new_foods: dict[str, NewFoodDraft] = field(default_factory=dict)
    pending_ingredient_name: str | None = None
    pending_ingredient_quantity: float | None = None
    dish_steps: str | None = None
    kcal_override: int | None = None
    unit: Unit | None = None
    category: Category | None = None
    kcal_ref: float | None = None
    edit_field: str | None = None


_WIZARD_KEY = "wizard"


def _get_wizard(context: WizardContextLike) -> WizardState | None:
    state = context.user_data.get(_WIZARD_KEY)
    if state is None:
        return None
    assert isinstance(state, WizardState)
    return state


def _set_wizard(context: WizardContextLike, state: WizardState) -> None:
    context.user_data[_WIZARD_KEY] = state


def _clear_wizard(context: WizardContextLike) -> None:
    context.user_data.pop(_WIZARD_KEY, None)


# --- keyboards -------------------------------------------------------------


def _meal_type_keyboard() -> Keyboard:
    row: ButtonRow = tuple((MEAL_TYPE_LABELS[mt], f"meal:{mt.value}") for mt in MealType)
    return (row,)


def _unit_keyboard() -> Keyboard:
    row: ButtonRow = tuple((UNIT_LABELS[u], f"unit:{u.value}") for u in Unit)
    return (row,)


def _category_keyboard() -> Keyboard:
    buttons: ButtonRow = tuple((CATEGORY_LABELS[c], f"cat:{c.value}") for c in CATEGORY_ORDER)
    return (buttons[:4], buttons[4:])


def _done_keyboard() -> Keyboard:
    return (((INGREDIENT_DONE_BUTTON, "ing:done"),),)


def _skip_keyboard() -> Keyboard:
    return (((STEPS_SKIP_BUTTON, "steps:skip"),),)


def _kcal_accept_keyboard() -> Keyboard:
    return (((KCAL_ACCEPT_BUTTON, "kcal:accept"),),)


def _kcal_ref_keyboard(seed_kcal_ref: float | None) -> Keyboard | None:
    if seed_kcal_ref is None:
        return None
    return (((KCAL_REF_ACCEPT_SEED_BUTTON, "kcalref:accept"),),)


def _confirm_keyboard() -> Keyboard:
    return (((CONFIRM_BUTTON, "confirm:yes"), (DISCARD_BUTTON, "confirm:no")),)


def _yes_no_keyboard(prefix: str) -> Keyboard:
    return (((YES_BUTTON, f"{prefix}:yes"), (NO_BUTTON, f"{prefix}:no")),)


_DISH_FIELDS: tuple[str, ...] = ("name", "meal_type", "ingredients", "steps", "kcal")
_FOOD_FIELDS: tuple[str, ...] = ("name", "unit", "category", "kcal_ref")


def _dish_field_keyboard() -> Keyboard:
    row: ButtonRow = tuple((DISH_FIELD_LABELS[f], f"field:{f}") for f in _DISH_FIELDS)
    return (row,)


def _food_field_keyboard() -> Keyboard:
    row: ButtonRow = tuple((FOOD_FIELD_LABELS[f], f"ffield:{f}") for f in _FOOD_FIELDS)
    return (row,)


# --- entry commands ----------------------------------------------------


async def _begin(
    update: UpdateLike,
    context: WizardContextLike,
    state: WizardState,
    prompt: str,
    keyboard: Keyboard | None = None,
) -> None:
    if _get_wizard(context) is not None:
        await update.reply_text(WIZARD_REPLACED_NOTICE)
    _set_wizard(context, state)
    await update.reply_text(prompt, reply_markup=keyboard)


async def _cmd_newdish(update: UpdateLike, context: WizardContextLike) -> None:
    await _begin(
        update, context, WizardState(kind=WizardKind.NEW_DISH, step=Step.NAME), NEWDISH_NAME_PROMPT
    )


cmd_newdish = private_only(_cmd_newdish)


async def _cmd_editdish(update: UpdateLike, context: WizardContextLike) -> None:
    await _begin(
        update,
        context,
        WizardState(kind=WizardKind.EDIT_DISH, step=Step.RESOLVE),
        EDIT_DISH_RESOLVE_PROMPT,
    )


cmd_editdish = private_only(_cmd_editdish)


async def _cmd_deletedish(update: UpdateLike, context: WizardContextLike) -> None:
    await _begin(
        update,
        context,
        WizardState(kind=WizardKind.DELETE_DISH, step=Step.RESOLVE),
        DELETE_DISH_RESOLVE_PROMPT,
    )


cmd_deletedish = private_only(_cmd_deletedish)


async def _cmd_newfood(update: UpdateLike, context: WizardContextLike) -> None:
    await _begin(
        update, context, WizardState(kind=WizardKind.NEW_FOOD, step=Step.NAME), NEWFOOD_NAME_PROMPT
    )


cmd_newfood = private_only(_cmd_newfood)


async def _cmd_editfood(update: UpdateLike, context: WizardContextLike) -> None:
    await _begin(
        update,
        context,
        WizardState(kind=WizardKind.EDIT_FOOD, step=Step.RESOLVE),
        EDIT_FOOD_RESOLVE_PROMPT,
    )


cmd_editfood = private_only(_cmd_editfood)


async def _cmd_deletefood(update: UpdateLike, context: WizardContextLike) -> None:
    await _begin(
        update,
        context,
        WizardState(kind=WizardKind.DELETE_FOOD, step=Step.RESOLVE),
        DELETE_FOOD_RESOLVE_PROMPT,
    )


cmd_deletefood = private_only(_cmd_deletefood)


async def _cmd_cancel(update: UpdateLike, context: WizardContextLike) -> None:
    if _get_wizard(context) is None:
        await update.reply_text(NO_WIZARD_IN_PROGRESS_MESSAGE)
        return
    _clear_wizard(context)
    await update.reply_text(WIZARD_CANCELLED_MESSAGE)


cmd_cancel = private_only(_cmd_cancel)


# --- shared helpers ------------------------------------------------------


def _current_new_food_name(state: WizardState) -> str | None:
    if state.kind in (WizardKind.NEW_DISH, WizardKind.EDIT_DISH):
        return state.pending_ingredient_name
    if state.kind is WizardKind.NEW_FOOD:
        return state.name
    return None


async def _prompt_next_ingredient(update: UpdateLike, state: WizardState) -> None:
    await update.reply_text(INGREDIENT_ADDED_PROMPT, reply_markup=_done_keyboard())


def _draft_dish_and_foods(
    conn: Connection, state: WizardState
) -> tuple[tuple[DishIngredient, ...], dict[int, Food]]:
    foods: dict[int, Food] = {}
    ingredients: list[DishIngredient] = []
    next_id = -1
    for ing in state.ingredients:
        if ing.food_id is not None:
            existing_food = repo.get_food(conn, ing.food_id)
            foods[existing_food.id] = existing_food
            ingredients.append(DishIngredient(food_id=existing_food.id, quantity=ing.quantity))
        else:
            draft = state.new_foods[ing.food_name.lower()]
            synthetic_id = next_id
            next_id -= 1
            foods[synthetic_id] = Food(
                id=synthetic_id,
                name=draft.name,
                unit=draft.unit,
                category=draft.category,
                kcal_ref=draft.kcal_ref,
            )
            ingredients.append(DishIngredient(food_id=synthetic_id, quantity=ing.quantity))
    return tuple(ingredients), foods


def _preview_dish_kcal(conn: Connection, state: WizardState) -> int:
    if state.kind is WizardKind.EDIT_DISH and state.edit_field != "ingredients":
        assert state.dish_id is not None
        current = repo.get_dish(conn, state.dish_id)
        foods = {i.food_id: repo.get_food(conn, i.food_id) for i in current.ingredients}
        return computed_kcal(current.ingredients, foods)
    ingredients, foods = _draft_dish_and_foods(conn, state)
    return computed_kcal(ingredients, foods)


async def _confirm_prompt_dish(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    if state.kind is WizardKind.EDIT_DISH:
        assert state.dish_id is not None
        current = repo.get_dish(conn, state.dish_id)
        name = state.name if state.edit_field == "name" else current.name
        meal_type = state.meal_type if state.edit_field == "meal_type" else current.meal_type
        steps = state.dish_steps if state.edit_field == "steps" else current.steps
        if state.edit_field == "ingredients":
            ingredients, foods = _draft_dish_and_foods(conn, state)
        else:
            ingredients = current.ingredients
            foods = {i.food_id: repo.get_food(conn, i.food_id) for i in current.ingredients}
        kcal_override = state.kcal_override if state.edit_field == "kcal" else current.kcal_override
        dish = Dish(
            id=current.id,
            name=name or current.name,
            meal_type=meal_type or current.meal_type,
            kcal=effective_kcal(ingredients, foods, kcal_override),
            ingredients=ingredients,
            kcal_override=kcal_override,
            steps=steps,
        )
    else:
        ingredients, foods = _draft_dish_and_foods(conn, state)
        dish = Dish(
            id=0,
            name=state.name or "",
            meal_type=state.meal_type or MealType.LUNCH,
            kcal=effective_kcal(ingredients, foods, state.kcal_override),
            ingredients=ingredients,
            kcal_override=state.kcal_override,
            steps=state.dish_steps,
        )
    state.step = Step.CONFIRM
    await update.reply_text(
        f"{CONFIRM_HEADER}\n{render_dish(dish, foods)}", reply_markup=_confirm_keyboard()
    )


async def _confirm_prompt_food(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    if state.kind is WizardKind.NEW_FOOD:
        food = Food(
            id=0,
            name=state.name or "",
            unit=state.unit or Unit.G,
            category=state.category or Category.OTHER,
            kcal_ref=state.kcal_ref if state.kcal_ref is not None else 0.0,
        )
    else:
        assert state.food_id is not None
        current_food = repo.get_food(conn, state.food_id)
        name = state.name if state.edit_field == "name" else current_food.name
        unit = state.unit if state.edit_field == "unit" else current_food.unit
        category = state.category if state.edit_field == "category" else current_food.category
        kcal_ref = (
            state.kcal_ref if state.edit_field in ("unit", "kcal_ref") else current_food.kcal_ref
        )
        food = Food(
            id=current_food.id,
            name=name or current_food.name,
            unit=unit or current_food.unit,
            category=category or current_food.category,
            kcal_ref=kcal_ref if kcal_ref is not None else current_food.kcal_ref,
        )
    state.step = Step.CONFIRM
    await update.reply_text(
        f"{CONFIRM_HEADER}\n{render_food_summary(food)}", reply_markup=_confirm_keyboard()
    )


async def _advance_to_kcal(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    state.step = Step.KCAL
    computed = _preview_dish_kcal(conn, state)
    await update.reply_text(render_kcal_step_prompt(computed), reply_markup=_kcal_accept_keyboard())


async def _kcal_ref_collected(
    update: UpdateLike,
    context: WizardContextLike,
    state: WizardState,
    conn: Connection,
    value: float,
) -> None:
    if state.kind in (WizardKind.NEW_DISH, WizardKind.EDIT_DISH):
        assert state.pending_ingredient_name is not None
        assert state.unit is not None and state.category is not None
        key = state.pending_ingredient_name.lower()
        state.new_foods[key] = NewFoodDraft(
            name=state.pending_ingredient_name,
            unit=state.unit,
            category=state.category,
            kcal_ref=value,
        )
        quantity = state.pending_ingredient_quantity
        assert quantity is not None
        state.ingredients.append(IngredientDraft(food_id=None, food_name=key, quantity=quantity))
        state.pending_ingredient_name = None
        state.pending_ingredient_quantity = None
        state.unit = None
        state.category = None
        state.step = Step.INGREDIENT
        await _prompt_next_ingredient(update, state)
        return
    state.kcal_ref = value
    await _confirm_prompt_food(update, context, state, conn)


# --- text step handlers --------------------------------------------------


async def _handle_name_text(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, text: str
) -> None:
    if not text:
        prompt = (
            NEWDISH_NAME_PROMPT
            if state.kind in (WizardKind.NEW_DISH, WizardKind.EDIT_DISH)
            else NEWFOOD_NAME_PROMPT
        )
        await update.reply_text(prompt)
        return
    state.name = text
    if state.kind is WizardKind.NEW_DISH:
        state.step = Step.MEAL_TYPE
        await update.reply_text(MEAL_TYPE_PROMPT, reply_markup=_meal_type_keyboard())
    elif state.kind is WizardKind.EDIT_DISH:
        await _confirm_prompt_dish(update, context, state, conn)
    elif state.kind is WizardKind.NEW_FOOD:
        state.step = Step.FOOD_UNIT
        seed = nutrition.seed_lookup(state.name)
        await update.reply_text(
            render_new_food_unit_prompt(seed.unit if seed else None), reply_markup=_unit_keyboard()
        )
    else:
        await _confirm_prompt_food(update, context, state, conn)


async def _handle_ingredient_text(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, text: str
) -> None:
    parts = text.rsplit(maxsplit=1)
    if len(parts) != 2:
        await update.reply_text(INGREDIENT_FORMAT_ERROR_MESSAGE)
        return
    name_part, qty_part = parts
    try:
        quantity = float(qty_part)
    except ValueError:
        await update.reply_text(INGREDIENT_QUANTITY_ERROR_MESSAGE)
        return
    if quantity <= 0:
        await update.reply_text(INGREDIENT_QUANTITY_ERROR_MESSAGE)
        return
    name_part = name_part.strip()
    key = name_part.lower()

    if key in state.new_foods:
        state.ingredients.append(IngredientDraft(food_id=None, food_name=key, quantity=quantity))
        await _prompt_next_ingredient(update, state)
        return

    exact = repo.get_food_by_exact_name(conn, name_part)
    if exact is not None and exact.active:
        state.ingredients.append(
            IngredientDraft(food_id=exact.id, food_name=exact.name.lower(), quantity=quantity)
        )
        await _prompt_next_ingredient(update, state)
        return

    matches = repo.find_foods_by_name(conn, name_part, limit=5)
    if matches:
        state.pending_ingredient_name = name_part
        state.pending_ingredient_quantity = quantity
        row: ButtonRow = tuple((f.name, f"ingfood:{f.id}") for f in matches[:5])
        await update.reply_text(FOOD_AMBIGUOUS_PROMPT, reply_markup=(row,))
        return

    state.pending_ingredient_name = name_part
    state.pending_ingredient_quantity = quantity
    state.step = Step.FOOD_UNIT
    seed = nutrition.seed_lookup(name_part)
    await update.reply_text(
        render_new_food_unit_prompt(seed.unit if seed else None), reply_markup=_unit_keyboard()
    )


async def _handle_kcal_ref_text(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, text: str
) -> None:
    try:
        value = float(text)
    except ValueError:
        await update.reply_text(FOOD_KCAL_INVALID_MESSAGE)
        return
    if value < 0:
        await update.reply_text(FOOD_KCAL_INVALID_MESSAGE)
        return
    await _kcal_ref_collected(update, context, state, conn, value)


async def _handle_kcal_text(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, text: str
) -> None:
    try:
        value = int(text)
    except ValueError:
        await update.reply_text(KCAL_INVALID_MESSAGE)
        return
    if value <= 0:
        await update.reply_text(KCAL_INVALID_MESSAGE)
        return
    state.kcal_override = value
    await _confirm_prompt_dish(update, context, state, conn)


async def _resolve_dish_text(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, text: str
) -> None:
    matches = repo.find_dishes_by_name(conn, text, limit=1000)
    exact = next((d for d in matches if d.name.lower() == text.strip().lower()), None)
    if exact is not None:
        await _after_resolve_dish(update, context, state, exact)
        return
    if not matches:
        await update.reply_text(DISH_NOT_FOUND_MESSAGE)
        _clear_wizard(context)
        return
    row: ButtonRow = tuple((d.name, f"wizdish:{d.id}") for d in matches[:5])
    await update.reply_text(DISH_FUZZY_PROMPT, reply_markup=(row,))


async def _resolve_food_text(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, text: str
) -> None:
    exact = repo.get_food_by_exact_name(conn, text)
    if exact is not None and exact.active:
        await _after_resolve_food(update, context, state, exact)
        return
    matches = repo.find_foods_by_name(conn, text, limit=5)
    if not matches:
        await update.reply_text(FOOD_NOT_FOUND_MESSAGE)
        _clear_wizard(context)
        return
    if len(matches) == 1:
        await _after_resolve_food(update, context, state, matches[0])
        return
    row: ButtonRow = tuple((f.name, f"wizfood:{f.id}") for f in matches[:5])
    await update.reply_text(FOOD_AMBIGUOUS_PROMPT, reply_markup=(row,))


async def _after_resolve_dish(
    update: UpdateLike, context: WizardContextLike, state: WizardState, dish: Dish
) -> None:
    state.dish_id = dish.id
    if state.kind is WizardKind.EDIT_DISH:
        state.step = Step.FIELD
        await update.reply_text(EDIT_FIELD_PROMPT, reply_markup=_dish_field_keyboard())
    else:
        state.step = Step.DELETE_CONFIRM
        await update.reply_text(
            render_delete_dish_confirm(dish), reply_markup=_yes_no_keyboard("deletedish")
        )


async def _after_resolve_food(
    update: UpdateLike, context: WizardContextLike, state: WizardState, food: Food
) -> None:
    state.food_id = food.id
    if state.kind is WizardKind.EDIT_FOOD:
        state.step = Step.FIELD
        await update.reply_text(EDIT_FIELD_PROMPT, reply_markup=_food_field_keyboard())
    else:
        state.step = Step.DELETE_CONFIRM
        await update.reply_text(
            render_delete_food_confirm(food), reply_markup=_yes_no_keyboard("deletefood")
        )


async def on_wizard_message(update: UpdateLike, context: WizardContextLike, text: str) -> None:
    state = _get_wizard(context)
    if state is None:
        return
    conn = get_conn(context)
    text = text.strip()

    if state.step is Step.NAME:
        await _handle_name_text(update, context, state, conn, text)
    elif state.step is Step.INGREDIENT:
        await _handle_ingredient_text(update, context, state, conn, text)
    elif state.step is Step.STEPS:
        state.dish_steps = text or None
        if state.kind is WizardKind.EDIT_DISH:
            await _confirm_prompt_dish(update, context, state, conn)
        else:
            await _advance_to_kcal(update, context, state, conn)
    elif state.step is Step.KCAL:
        await _handle_kcal_text(update, context, state, conn, text)
    elif state.step is Step.FOOD_KCAL_REF:
        await _handle_kcal_ref_text(update, context, state, conn, text)
    elif state.step is Step.RESOLVE:
        if state.kind in (WizardKind.EDIT_DISH, WizardKind.DELETE_DISH):
            await _resolve_dish_text(update, context, state, conn, text)
        else:
            await _resolve_food_text(update, context, state, conn, text)
    # MEAL_TYPE, FOOD_UNIT, FOOD_CATEGORY, FIELD, CONFIRM and DELETE_CONFIRM
    # are button-only steps; a stray text message is simply ignored.


# --- callback step handlers -----------------------------------------------


async def _handle_meal_type_callback(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, value: str
) -> None:
    state.meal_type = MealType(value)
    if state.kind is WizardKind.EDIT_DISH:
        await _confirm_prompt_dish(update, context, state, conn)
        return
    state.step = Step.INGREDIENT
    await update.reply_text(INGREDIENT_PROMPT)


async def _handle_ingredient_done(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    if not state.ingredients:
        await update.reply_text(INGREDIENT_NEEDS_ONE_MESSAGE)
        return
    if state.kind is WizardKind.EDIT_DISH:
        await _confirm_prompt_dish(update, context, state, conn)
        return
    state.step = Step.STEPS
    await update.reply_text(STEPS_PROMPT, reply_markup=_skip_keyboard())


async def _handle_ingfood_callback(
    update: UpdateLike,
    context: WizardContextLike,
    state: WizardState,
    conn: Connection,
    food_id: int,
) -> None:
    food = repo.get_food(conn, food_id)
    quantity = state.pending_ingredient_quantity
    assert quantity is not None
    state.ingredients.append(
        IngredientDraft(food_id=food.id, food_name=food.name.lower(), quantity=quantity)
    )
    state.pending_ingredient_name = None
    state.pending_ingredient_quantity = None
    state.step = Step.INGREDIENT
    await _prompt_next_ingredient(update, state)


async def _handle_unit_callback(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, value: str
) -> None:
    state.unit = Unit(value)
    if state.kind is WizardKind.EDIT_FOOD and state.edit_field == "unit":
        state.step = Step.FOOD_KCAL_REF
        await update.reply_text(FOOD_KCAL_PROMPT)
        return
    state.step = Step.FOOD_CATEGORY
    name = _current_new_food_name(state)
    seed = nutrition.seed_lookup(name) if name else None
    await update.reply_text(
        render_new_food_category_prompt(seed.category if seed else None),
        reply_markup=_category_keyboard(),
    )


async def _handle_category_callback(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection, value: str
) -> None:
    state.category = Category(value)
    if state.kind is WizardKind.EDIT_FOOD and state.edit_field == "category":
        await _confirm_prompt_food(update, context, state, conn)
        return
    state.step = Step.FOOD_KCAL_REF
    name = _current_new_food_name(state)
    seed = nutrition.seed_lookup(name) if name else None
    await update.reply_text(
        render_new_food_kcal_prompt(seed.kcal_ref if seed else None),
        reply_markup=_kcal_ref_keyboard(seed.kcal_ref if seed else None),
    )


async def _handle_kcal_ref_accept_callback(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    name = _current_new_food_name(state)
    seed = nutrition.seed_lookup(name) if name else None
    if seed is None:
        return
    await _kcal_ref_collected(update, context, state, conn, seed.kcal_ref)


async def _handle_dish_field_callback(
    update: UpdateLike,
    context: WizardContextLike,
    state: WizardState,
    conn: Connection,
    field_name: str,
) -> None:
    state.edit_field = field_name
    if field_name == "name":
        state.step = Step.NAME
        await update.reply_text(NEWDISH_NAME_PROMPT)
    elif field_name == "meal_type":
        state.step = Step.MEAL_TYPE
        await update.reply_text(MEAL_TYPE_PROMPT, reply_markup=_meal_type_keyboard())
    elif field_name == "ingredients":
        state.ingredients = []
        state.new_foods = {}
        state.step = Step.INGREDIENT
        await update.reply_text(INGREDIENT_PROMPT)
    elif field_name == "steps":
        state.step = Step.STEPS
        await update.reply_text(STEPS_PROMPT, reply_markup=_skip_keyboard())
    else:
        state.step = Step.KCAL
        computed = _preview_dish_kcal(conn, state)
        await update.reply_text(
            render_kcal_step_prompt(computed), reply_markup=_kcal_accept_keyboard()
        )


async def _handle_food_field_callback(
    update: UpdateLike,
    context: WizardContextLike,
    state: WizardState,
    conn: Connection,
    field_name: str,
) -> None:
    state.edit_field = field_name
    if field_name == "name":
        state.step = Step.NAME
        await update.reply_text(NEWFOOD_NAME_PROMPT)
    elif field_name == "unit":
        state.step = Step.FOOD_UNIT
        await update.reply_text(FOOD_UNIT_PROMPT, reply_markup=_unit_keyboard())
    elif field_name == "category":
        state.step = Step.FOOD_CATEGORY
        await update.reply_text(FOOD_CATEGORY_PROMPT, reply_markup=_category_keyboard())
    else:
        state.step = Step.FOOD_KCAL_REF
        await update.reply_text(FOOD_KCAL_PROMPT)


async def _finalize_dish(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    if state.kind is WizardKind.NEW_DISH:
        new_foods = [
            repo.NewFoodSpec(name=d.name, unit=d.unit, category=d.category, kcal_ref=d.kcal_ref)
            for d in state.new_foods.values()
        ]
        ingredient_refs: list[repo.IngredientRef] = [
            (i.food_id, None if i.food_id is not None else i.food_name, i.quantity)
            for i in state.ingredients
        ]
        try:
            dish = repo.create_dish_with_new_foods(
                conn,
                name=state.name or "",
                meal_type=state.meal_type or MealType.LUNCH,
                new_foods=new_foods,
                ingredients=ingredient_refs,
                kcal_override=state.kcal_override,
                steps=state.dish_steps,
            )
        except ValueError:
            await update.reply_text(DISH_NAME_DUPLICATE_MESSAGE)
            _clear_wizard(context)
            return
        _clear_wizard(context)
        await update.reply_text(render_dish_created(dish.name))
        return

    assert state.dish_id is not None
    try:
        if state.edit_field == "name":
            repo.update_dish(conn, state.dish_id, name=state.name)
        elif state.edit_field == "meal_type":
            repo.update_dish(conn, state.dish_id, meal_type=state.meal_type)
        elif state.edit_field == "ingredients":
            if state.new_foods:
                new_foods = [
                    repo.NewFoodSpec(
                        name=d.name, unit=d.unit, category=d.category, kcal_ref=d.kcal_ref
                    )
                    for d in state.new_foods.values()
                ]
                ingredient_refs = [
                    (i.food_id, None if i.food_id is not None else i.food_name, i.quantity)
                    for i in state.ingredients
                ]
                repo.update_dish_ingredients_with_new_foods(
                    conn, state.dish_id, new_foods=new_foods, ingredients=ingredient_refs
                )
            else:
                resolved_ingredients: list[DishIngredient] = []
                for i in state.ingredients:
                    assert i.food_id is not None
                    resolved_ingredients.append(
                        DishIngredient(food_id=i.food_id, quantity=i.quantity)
                    )
                repo.update_dish(conn, state.dish_id, ingredients=resolved_ingredients)
        elif state.edit_field == "steps":
            repo.update_dish(conn, state.dish_id, steps=state.dish_steps)
        else:
            repo.update_dish(conn, state.dish_id, kcal_override=state.kcal_override)
    except ValueError:
        await update.reply_text(DISH_NAME_DUPLICATE_MESSAGE)
        _clear_wizard(context)
        return
    dish = repo.get_dish(conn, state.dish_id)
    _clear_wizard(context)
    await update.reply_text(render_dish_updated(dish.name))


async def _finalize_food(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    if state.kind is WizardKind.NEW_FOOD:
        try:
            food = repo.create_food(
                conn,
                name=state.name or "",
                unit=state.unit or Unit.G,
                category=state.category or Category.OTHER,
                kcal_ref=state.kcal_ref if state.kcal_ref is not None else 0.0,
            )
        except ValueError:
            await update.reply_text(DISH_NAME_DUPLICATE_MESSAGE)
            _clear_wizard(context)
            return
        _clear_wizard(context)
        await update.reply_text(render_food_created(food.name))
        return

    assert state.food_id is not None
    try:
        if state.edit_field == "name":
            food = repo.update_food(conn, state.food_id, name=state.name)
        elif state.edit_field == "category":
            food = repo.update_food(conn, state.food_id, category=state.category)
        elif state.edit_field == "unit":
            food = repo.update_food(conn, state.food_id, unit=state.unit, kcal_ref=state.kcal_ref)
        else:
            food = repo.update_food(conn, state.food_id, kcal_ref=state.kcal_ref)
    except ValueError:
        await update.reply_text(DISH_NAME_DUPLICATE_MESSAGE)
        _clear_wizard(context)
        return
    _clear_wizard(context)
    await update.reply_text(render_food_updated(food.name))


async def _finalize(
    update: UpdateLike, context: WizardContextLike, state: WizardState, conn: Connection
) -> None:
    if state.kind in (WizardKind.NEW_DISH, WizardKind.EDIT_DISH):
        await _finalize_dish(update, context, state, conn)
    else:
        await _finalize_food(update, context, state, conn)


async def _discard(update: UpdateLike, context: WizardContextLike, state: WizardState) -> None:
    _clear_wizard(context)
    if state.kind in (WizardKind.NEW_DISH, WizardKind.EDIT_DISH):
        await update.reply_text(DISH_DISCARDED_MESSAGE)
    else:
        await update.reply_text(FOOD_DISCARDED_MESSAGE)


async def on_wizard_callback(update: CallbackUpdateLike, context: WizardContextLike) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    state = _get_wizard(context)
    await query.answer()
    if state is None:
        return

    conn = get_conn(context)
    prefix, _, value = query.data.partition(":")

    if prefix == "meal" and state.step is Step.MEAL_TYPE:
        await _handle_meal_type_callback(update, context, state, conn, value)
    elif prefix == "ing" and value == "done" and state.step is Step.INGREDIENT:
        await _handle_ingredient_done(update, context, state, conn)
    elif prefix == "ingfood" and state.step is Step.INGREDIENT:
        await _handle_ingfood_callback(update, context, state, conn, int(value))
    elif prefix == "unit" and state.step is Step.FOOD_UNIT:
        await _handle_unit_callback(update, context, state, conn, value)
    elif prefix == "cat" and state.step is Step.FOOD_CATEGORY:
        await _handle_category_callback(update, context, state, conn, value)
    elif prefix == "kcalref" and value == "accept" and state.step is Step.FOOD_KCAL_REF:
        await _handle_kcal_ref_accept_callback(update, context, state, conn)
    elif prefix == "steps" and value == "skip" and state.step is Step.STEPS:
        state.dish_steps = None
        if state.kind is WizardKind.EDIT_DISH:
            await _confirm_prompt_dish(update, context, state, conn)
        else:
            await _advance_to_kcal(update, context, state, conn)
    elif prefix == "kcal" and value == "accept" and state.step is Step.KCAL:
        state.kcal_override = None
        await _confirm_prompt_dish(update, context, state, conn)
    elif prefix == "confirm" and state.step is Step.CONFIRM:
        if value == "yes":
            await _finalize(update, context, state, conn)
        else:
            await _discard(update, context, state)
    elif prefix == "wizdish" and state.step is Step.RESOLVE:
        dish = repo.get_dish(conn, int(value))
        await _after_resolve_dish(update, context, state, dish)
    elif prefix == "wizfood" and state.step is Step.RESOLVE:
        food = repo.get_food(conn, int(value))
        await _after_resolve_food(update, context, state, food)
    elif prefix == "field" and state.step is Step.FIELD:
        await _handle_dish_field_callback(update, context, state, conn, value)
    elif prefix == "ffield" and state.step is Step.FIELD:
        await _handle_food_field_callback(update, context, state, conn, value)
    elif prefix == "deletedish" and state.step is Step.DELETE_CONFIRM:
        assert state.dish_id is not None
        if value == "yes":
            today = get_clock(context)()
            repo.deactivate_dish(conn, state.dish_id, today)
            dish = repo.get_dish(conn, state.dish_id)
            _clear_wizard(context)
            await update.reply_text(render_delete_dish_done(dish.name))
        else:
            _clear_wizard(context)
            await update.reply_text(DELETE_CANCELLED_MESSAGE)
    elif prefix == "deletefood" and state.step is Step.DELETE_CONFIRM:
        assert state.food_id is not None
        if value == "yes":
            try:
                repo.deactivate_food(conn, state.food_id)
            except repo.FoodInUse as exc:
                _clear_wizard(context)
                await update.reply_text(render_food_in_use(exc.dish_names))
                return
            food = repo.get_food(conn, state.food_id)
            _clear_wizard(context)
            await update.reply_text(render_delete_food_done(food.name))
        else:
            _clear_wizard(context)
            await update.reply_text(DELETE_CANCELLED_MESSAGE)
