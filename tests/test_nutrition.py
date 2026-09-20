import pytest

from meal_planning_bot.models import Category, DishIngredient, Food, Unit
from meal_planning_bot.nutrition import _seed, computed_kcal, effective_kcal, seed_lookup

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


def test_every_seed_entry_is_well_formed() -> None:
    for name, entry in _seed().items():
        assert name == name.lower()
        assert isinstance(entry.unit, Unit)
        assert isinstance(entry.category, Category)
        assert 0 <= entry.kcal_ref <= 900, f"{name} has an implausible kcal_ref"


ANCHORS = {
    "aceite de oliva": 884,
    "arroz": 360,
    "pollo": 165,
    "huevo": 78,
    "pan": 265,
    "pasta": 371,
    "lenteja": 353,
    "atun": 132,
    "leche": 64,
    "platano": 89,
}


@pytest.mark.parametrize(("name", "expected"), ANCHORS.items())
def test_anchor_values(name: str, expected: int) -> None:
    entry = seed_lookup(name)
    assert entry is not None
    assert abs(entry.kcal_ref - expected) <= 5
