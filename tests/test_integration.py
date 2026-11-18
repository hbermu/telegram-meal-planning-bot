from datetime import date
from pathlib import Path
from random import Random
from sqlite3 import Connection
from typing import Any

from meal_planning_bot import repo, scheduler
from meal_planning_bot.__main__ import build_application
from meal_planning_bot.anchor import Anchors
from meal_planning_bot.config import Config
from meal_planning_bot.db import open_database
from meal_planning_bot.formatting import (
    MEAL_TYPE_LABELS,
    NO_PLAN_MESSAGE,
    OVERRIDE_DAY_PROMPT,
    OVERRIDE_MARK,
    PRIVATE_ONLY_MESSAGE,
)
from meal_planning_bot.models import Category, DishIngredient, MealType, Unit
from meal_planning_bot.weeks import current_week_start
from tests.fakes import Driver, FakeBot

ALLOWED_USER = 1001
OUTSIDER_USER = 9999
GROUP_CHAT = -100123456
PRIVATE_CHAT = ALLOWED_USER  # a private chat's id equals the user's id

TODAY = date(2026, 9, 15)  # a Tuesday; the week starts Monday 2026-09-14

# Unit, category and reference-quantity calories for every food the six
# dishes below need, keyed by the name typed into the wizard. Every dinner
# shares "Caldo" so its weekly total never depends on which dinner dish a
# given day drew; "Pasta" and "Calabaza" differ between the two dinners so
# a swap between them is visible in the shopping list.
FOOD_SPECS: dict[str, tuple[str, str, str]] = {
    "Pan": ("g", "bakery", "300"),
    "Mantequilla": ("g", "dairy_eggs", "700"),
    "Yogur": ("g", "dairy_eggs", "160"),
    "Platano": ("unit", "produce", "200"),
    "Arroz": ("g", "pantry", "350"),
    "Pollo": ("g", "meat_fish", "200"),
    "Caldo": ("ml", "pantry", "50"),
    "Pasta": ("g", "pantry", "500"),
    "Calabaza": ("g", "produce", "250"),
}

DISH_SPECS: list[tuple[str, str, list[tuple[str, float]]]] = [
    ("Tostada", "breakfast", [("Pan", 80), ("Mantequilla", 10)]),
    ("Yogur con fruta", "snack", [("Yogur", 125)]),
    ("Platano", "snack", [("Platano", 1)]),
    ("Arroz con pollo", "lunch", [("Arroz", 100), ("Pollo", 150)]),
    ("Sopa de pasta", "dinner", [("Caldo", 300), ("Pasta", 100)]),
    ("Crema de calabaza", "dinner", [("Caldo", 300), ("Calabaza", 200)]),
]


def _first_button(markup: Any) -> str:
    """The callback data behind the first inline button of a reply."""
    return str(markup.inline_keyboard[0][0].callback_data)


def _config(tmp_path: Path, allowed: frozenset[int] = frozenset({ALLOWED_USER})) -> Config:
    return Config(
        token="test-token",
        allowed_user_ids=allowed,
        group_chat_id=GROUP_CHAT,
        db_path=tmp_path / "mealbot.db",
        timezone="UTC",
        log_level="INFO",
        allow_partial_plan=False,
    )


async def _add_ingredient(user: Driver, known_foods: set[str], name: str, quantity: float) -> None:
    await user.send(f"{name} {quantity:g}")
    if name not in known_foods:
        unit, category, kcal_ref = FOOD_SPECS[name]
        await user.tap(f"unit:{unit}")
        await user.tap(f"cat:{category}")
        await user.send(kcal_ref)
        known_foods.add(name)


async def _create_dish_via_wizard(
    user: Driver,
    known_foods: set[str],
    name: str,
    meal_type: str,
    ingredients: list[tuple[str, float]],
) -> str:
    await user.send("/newdish")
    await user.send(name)
    await user.tap(f"meal:{meal_type}")
    for food_name, quantity in ingredients:
        await _add_ingredient(user, known_foods, food_name, quantity)
    await user.tap("ing:done")
    await user.tap("steps:skip")
    await user.tap("kcal:accept")
    return await user.tap("confirm:yes")


async def _build_six_dish_catalogue(user: Driver) -> None:
    known_foods: set[str] = set()
    for name, meal_type, ingredients in DISH_SPECS:
        await _create_dish_via_wizard(user, known_foods, name, meal_type, ingredients)


def _seed_catalogue_via_repo(conn: Connection) -> None:
    foods: dict[str, int] = {}
    for name, (unit_val, category_val, kcal_ref) in FOOD_SPECS.items():
        food = repo.create_food(
            conn,
            name=name,
            unit=Unit(unit_val),
            category=Category(category_val),
            kcal_ref=float(kcal_ref),
        )
        foods[name] = food.id
    for name, meal_type, ingredients in DISH_SPECS:
        repo.create_dish(
            conn,
            name=name,
            meal_type=MealType(meal_type),
            ingredients=[DishIngredient(food_id=foods[n], quantity=q) for n, q in ingredients],
        )


async def test_full_journey(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    app.bot_data["rng"] = Random(0)
    await app.initialize()
    user = Driver(app, bot, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    await _build_six_dish_catalogue(user)
    assert conn.execute("SELECT count(*) FROM dishes").fetchone()[0] == 6
    assert conn.execute("SELECT count(*) FROM foods").fetchone()[0] == 9

    # The wizard steps above are driven by sending their callback data directly, which
    # would still pass if telegram_bridge dropped every keyboard on the way out and the
    # buttons never reached anyone. Assert the bot actually sent some.
    assert any(sent.markup is not None for sent in bot.sent + bot.edited)

    assert (await user.send("/plan")) == NO_PLAN_MESSAGE

    await user.send("/regenerate")
    plan_text = await user.send("/plan")
    # 25 dish lines each carrying "(N kcal)" plus 5 "Total: N kcal" lines.
    assert plan_text.count("kcal") == 30

    shopping = await user.send("/shopping")
    # Every dish below is reused on all five weekdays (each meal type's
    # cooldown is at most 1 day by default, or relaxed to 1 by the ladder),
    # so every food's weekly total is exactly its per-dish quantity times 5 -
    # except the two dinners, which split the week between them; under the
    # rng seeded above that split is 4 days of Crema de calabaza (200 g) to
    # 1 day of Sopa de pasta (100 g), and both share 300 ml of Caldo daily.
    assert "Pan: 400 g" in shopping  # 80 g x 5
    assert "Mantequilla: 50 g" in shopping  # 10 g x 5
    assert "Yogur: 625 g" in shopping  # 125 g x 5
    assert "Platano: 5 ud" in shopping  # 1 ud x 5
    assert "Arroz: 500 g" in shopping  # 100 g x 5
    assert "Pollo: 750 g" in shopping  # 150 g x 5
    assert "Caldo: 1500 ml" in shopping  # 300 ml x 5
    assert "Pasta: 100 g" in shopping  # 100 g x 1
    assert "Calabaza: 800 g" in shopping  # 200 g x 4

    before = await user.send("/plan")
    await user.send("/swap martes cena")
    after = await user.send("/plan")
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines)
    pairs = zip(before_lines, after_lines, strict=True)
    differing = [i for i, (b, a) in enumerate(pairs) if b != a]
    assert len(differing) == 1
    assert "Cena: Sopa de pasta (650 kcal)" in after

    shopping_after = await user.send("/shopping")
    # Swapping Tuesday's dinner from Crema de calabaza to Sopa de pasta moves
    # one day's worth between the two: -200 g calabaza, +100 g pasta.
    assert "Calabaza: 600 g" in shopping_after
    assert "Pasta: 200 g" in shopping_after
    assert "Pan: 400 g" in shopping_after  # untouched by the swap

    # /dishes paginates over six dishes in one page, so it carries no keyboard; the dish
    # card reached through a fuzzy match does. Both go through telegram_bridge.to_markup.
    bot.messages.clear()
    await user.send("/dish sopa")
    assert any(message.markup is not None for message in bot.messages), (
        "a fuzzy /dish match must offer inline buttons; to_markup dropped them"
    )

    today_text = await user.send("/today")
    # after = "header\n\nMonday\n\nTuesday\n\n...": index 2 is Tuesday's block.
    tuesday_block = after.split("\n\n")[2]
    assert today_text == tuesday_block

    await app.shutdown()


async def test_navigation_reuses_one_message_and_takes_the_commands_away(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    _seed_catalogue_via_repo(conn)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    app.bot_data["rng"] = Random(0)
    await app.initialize()
    user = Driver(app, bot, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    await user.send("/help")
    anchor = bot.sent[-1].message_id
    await user.send("/regenerate")
    await user.send("/plan")
    await user.send("/dishes")

    assert len(bot.sent) == 1, "only the first reply posts a message; the rest edit it"
    assert {edit.message_id for edit in bot.edited} == {anchor}
    # Every command the user typed is off the screen.
    assert len(bot.deleted) == 4
    assert {chat_id for chat_id, _ in bot.deleted} == {PRIVATE_CHAT}
    assert len(bot.edited) == 3

    # A tap keeps navigating in that same message.
    await user.send("/dish sopa")
    await user.tap(_first_button(bot.edited[-1].markup))
    assert bot.edited[-1].message_id == anchor
    assert len(bot.sent) == 1

    # The shopping list is content: it is posted, and the menu stays put.
    await user.send("/shopping")
    assert len(bot.sent) == 2
    await user.send("/plan")
    assert bot.edited[-1].message_id == anchor

    await app.shutdown()


async def test_a_tap_after_a_restart_adopts_the_menu_on_screen(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    _seed_catalogue_via_repo(conn)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    await app.initialize()
    user = Driver(app, bot, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    await user.send("/dish sopa")
    button = _first_button(bot.sent[-1].markup)

    # A restart forgets the anchor while the menu is still on screen.
    app.bot_data["anchors"] = Anchors()
    bot.sent.clear()
    bot.edited.clear()

    await user.tap(button)

    assert bot.sent == [], "the tap must adopt the message it came from, not post a new one"
    assert len(bot.edited) == 1

    await app.shutdown()


async def test_a_hand_picked_meal_reaches_the_plan_the_list_and_the_next_draw(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    _seed_catalogue_via_repo(conn)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    app.bot_data["rng"] = Random(0)
    await app.initialize()
    user = Driver(app, bot, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    await user.send("/regenerate")

    # Tuesday's dinner becomes a dish of our choosing, pinned.
    chosen = await user.send("/override hoy cena Sopa de pasta")
    assert "Cena: Sopa de pasta" in chosen
    assert OVERRIDE_MARK in chosen

    shopping = await user.send("/shopping")
    assert "Pasta" in shopping

    # And Wednesday's lunch is not cooked at all.
    eaten_out = await user.send("/override miercoles comida fuera en el chino")
    assert "Comida: en el chino" in eaten_out

    plan = await user.send("/plan")
    assert plan.count(OVERRIDE_MARK) == 2

    # A fresh draw of the same week keeps both and re-draws the rest.
    await user.send("/regenerate")
    after = await user.send("/plan")
    assert "Cena: Sopa de pasta" in after
    assert "Comida: en el chino" in after
    assert after.count(OVERRIDE_MARK) == 2

    # The slot nobody cooks buys nothing: Wednesday's lunch rice is gone from
    # the week's total, which is now four lunches' worth instead of five.
    list_after = await user.send("/shopping")
    assert "Arroz: 400 g" in list_after

    await app.shutdown()


async def test_a_custom_dish_is_typed_into_the_button_flow(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    _seed_catalogue_via_repo(conn)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    app.bot_data["rng"] = Random(0)
    await app.initialize()
    user = Driver(app, bot, chat_id=GROUP_CHAT, user_id=ALLOWED_USER, chat_type="group")

    await user.send("/regenerate")
    days = await user.send("/override")
    assert days == OVERRIDE_DAY_PROMPT
    today = _first_button(bot.messages[-1].markup)
    assert today == "ov:slot:now:1"

    await user.tap(today)
    await user.tap("ov:pick:now:1:dinner:1")
    assert _first_button(bot.messages[-1].markup) == "ov:custom:now:1:dinner"
    await user.tap("ov:custom:now:1:dinner")

    anchor = user.anchor_id
    bot.deleted.clear()
    chosen = await user.send("Pizza casera")

    assert "Cena: Pizza casera" in chosen
    assert OVERRIDE_MARK in chosen
    assert user.anchor_id == anchor, "the pinned day must replace the prompt in place"
    assert bot.deleted == [(GROUP_CHAT, user._message_id)], "the typed dish must leave the chat"

    # The prompt is answered: the next message is chatter, not another dish.
    bot.messages.clear()
    await user.send("Gracias")
    assert bot.messages == []

    await app.shutdown()


async def test_persistence_across_restart(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn1 = open_database(config.db_path)
    bot1 = FakeBot()
    app1 = build_application(config, conn1, bot=bot1, clock=lambda: TODAY)
    app1.bot_data["rng"] = Random(0)
    await app1.initialize()
    user1 = Driver(app1, bot1, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    await _build_six_dish_catalogue(user1)
    await user1.send("/regenerate")
    plan_before = await user1.send("/plan")
    dishes_before = await user1.send("/dishes")

    await app1.shutdown()
    conn1.close()

    conn2 = open_database(config.db_path)
    bot2 = FakeBot()
    app2 = build_application(config, conn2, bot=bot2, clock=lambda: TODAY)
    await app2.initialize()
    user2 = Driver(app2, bot2, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    plan_after = await user2.send("/plan")
    dishes_after = await user2.send("/dishes")

    assert plan_after == plan_before
    assert dishes_after == dishes_before

    await app2.shutdown()
    conn2.close()


async def test_disallowed_user_produces_no_calls(tmp_path: Path) -> None:
    config = _config(tmp_path)  # only ALLOWED_USER is on the allow-list
    conn = open_database(config.db_path)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    app.bot_data["rng"] = Random(0)
    await app.initialize()
    intruder = Driver(app, bot, chat_id=OUTSIDER_USER, user_id=OUTSIDER_USER)

    await _build_six_dish_catalogue(intruder)
    await intruder.send("/plan")
    await intruder.send("/regenerate")
    await intruder.send("/shopping")
    await intruder.send("/swap martes cena")
    await intruder.send("/today")

    assert bot.sent == []
    assert bot.edited == []
    assert bot.answered == []
    assert conn.execute("SELECT count(*) FROM dishes").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM foods").fetchone()[0] == 0

    await app.shutdown()


async def test_newdish_from_group_redirects_and_starts_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    await app.initialize()
    member = Driver(app, bot, chat_id=GROUP_CHAT, user_id=ALLOWED_USER, chat_type="group")

    reply = await member.send("/newdish")

    assert reply == PRIVATE_ONLY_MESSAGE
    assert "wizard" not in app.user_data[ALLOWED_USER]

    await app.shutdown()


async def test_scheduled_jobs_post_only_to_the_group(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    _seed_catalogue_via_repo(conn)
    bot = FakeBot()
    rng = Random(0)

    await scheduler.weekly_job(bot, conn, config, TODAY, rng)
    await scheduler.daily_job(bot, conn, config, TODAY, rng)

    assert bot.sent
    chat_ids = {sent.chat_id for sent in bot.sent}
    assert chat_ids == {config.group_chat_id}
    # Two distinct chat ids are genuinely in play here: the group the jobs
    # must post to, and the private chat id an allow-listed user would use -
    # the assertion above only means something because the two differ.
    assert config.group_chat_id != PRIVATE_CHAT
    assert PRIVATE_CHAT not in chat_ids


async def test_regenerate_on_empty_catalogue_diagnoses_and_saves_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conn = open_database(config.db_path)
    bot = FakeBot()
    app = build_application(config, conn, bot=bot, clock=lambda: TODAY)
    await app.initialize()
    user = Driver(app, bot, chat_id=PRIVATE_CHAT, user_id=ALLOWED_USER)

    reply = await user.send("/regenerate")

    for meal_type in MealType:
        assert MEAL_TYPE_LABELS[meal_type] in reply
    assert repo.get_plan(conn, current_week_start(TODAY)) is None

    await app.shutdown()
