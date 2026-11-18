"""The inline keyboards shared between the menu and the commands, and the
`menu:` callback vocabulary they emit.

Every navigation state lives in the callback data, so the bot keeps no menu
state and a restart never strands a half-walked menu. The labels come from
`formatting.py`, which owns every user-visible string; this module only decides
what sits next to what.
"""

from meal_planning_bot.formatting import (
    ARCHIVED_DISHES_BUTTON,
    ARCHIVED_FOODS_BUTTON,
    BACK_BUTTON,
    CATALOGUE_BUTTON,
    CURRENT_WEEK_BUTTON,
    DISHES_BUTTON,
    FOODS_BUTTON,
    HELP_BUTTON,
    NEXT_WEEK_BUTTON,
    NO_BUTTON,
    OVERRIDE_CHANGE_BUTTON,
    PLAN_BUTTON,
    REGENERATE_BUTTON,
    SETTINGS_BUTTON,
    SHOPPING_BUTTON,
    TODAY_BUTTON,
    YES_BUTTON,
)
from meal_planning_bot.handlers import ButtonRow, Keyboard

MAIN = "menu:main"
CATALOGUE = "menu:catalog"
SETTINGS = "menu:settings"
HELP = "menu:help"
TODAY = "menu:today"

# A week is addressed as `now` or `next` throughout the menu, mirroring the
# optional `siguiente` keyword the typed commands take.
NOW = "now"
NEXT = "next"


def week_token(is_next: bool) -> str:
    return NEXT if is_next else NOW


def main_menu() -> Keyboard:
    return (
        ((PLAN_BUTTON, f"menu:plan:{NOW}"), (TODAY_BUTTON, TODAY)),
        ((SHOPPING_BUTTON, f"menu:shopping:{NOW}"), (CATALOGUE_BUTTON, CATALOGUE)),
        ((SETTINGS_BUTTON, SETTINGS), (HELP_BUTTON, HELP)),
    )


def plan_menu(is_next: bool) -> Keyboard:
    week = week_token(is_next)
    other = (
        (CURRENT_WEEK_BUTTON, f"menu:plan:{NOW}")
        if is_next
        else (NEXT_WEEK_BUTTON, f"menu:plan:{NEXT}")
    )
    return (
        ((OVERRIDE_CHANGE_BUTTON, f"ov:day:{week}"),),
        ((REGENERATE_BUTTON, f"menu:regen:{week}"), (SHOPPING_BUTTON, f"menu:shopping:{week}")),
        (other,),
        ((BACK_BUTTON, MAIN),),
    )


def regenerate_confirm(is_next: bool) -> Keyboard:
    week = week_token(is_next)
    return (((YES_BUTTON, f"menu:regenyes:{week}"), (NO_BUTTON, f"menu:plan:{week}")),)


def catalogue_menu() -> Keyboard:
    return (
        ((DISHES_BUTTON, "dishes:1:0"), (FOODS_BUTTON, "foods:1:0")),
        ((ARCHIVED_DISHES_BUTTON, "dishes:1:1"), (ARCHIVED_FOODS_BUTTON, "foods:1:1")),
        ((BACK_BUTTON, MAIN),),
    )


def back_row(target: str) -> ButtonRow:
    return ((BACK_BUTTON, target),)


def back_to(target: str) -> Keyboard:
    return (back_row(target),)
