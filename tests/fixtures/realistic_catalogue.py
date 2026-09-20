from meal_planning_bot.models import Dish, DishIngredient, MealType

FOODS: dict[str, int] = {
    "rice": 1,
    "chicken": 2,
    "eggs": 3,
    "oats": 4,
    "yoghurt": 5,
    "bread": 6,
    "potato": 7,
    "salmon": 8,
    "beef": 9,
    "pasta": 10,
    "cheese": 11,
    "tomato": 12,
    "lettuce": 13,
    "banana": 14,
    "milk": 15,
    "beans": 16,
    "tofu": 17,
    "turkey": 18,
    "broccoli": 19,
    "spinach": 20,
    "quinoa": 21,
    "lentils": 22,
    "pork": 23,
    "tuna": 24,
    "avocado": 25,
    "nuts": 26,
    "honey": 27,
    "peanut_butter": 28,
    "granola": 29,
    "berries": 30,
    "pepper": 31,
    "onion": 32,
    "garlic": 33,
    "olive_oil": 34,
    "zucchini": 35,
    "carrot": 36,
    "corn": 37,
    "shrimp": 38,
    "chickpeas": 39,
    "apple": 40,
    "flour": 41,
}


def _dish(id: int, name: str, meal_type: MealType, kcal: int, foods: list[str]) -> Dish:
    return Dish(
        id=id,
        name=name,
        meal_type=meal_type,
        kcal=kcal,
        ingredients=tuple(DishIngredient(food_id=FOODS[f], quantity=100.0) for f in foods),
    )


_BREAKFASTS = [
    ("Oatmeal with banana", 350, ["oats", "banana", "milk"]),
    ("Greek yoghurt with granola", 320, ["yoghurt", "granola", "honey"]),
    ("Scrambled eggs with toast", 400, ["eggs", "bread"]),
    ("Avocado toast with eggs", 420, ["bread", "avocado", "eggs"]),
    ("Yoghurt with berries", 280, ["yoghurt", "berries"]),
    ("Oatmeal with peanut butter", 380, ["oats", "peanut_butter", "milk"]),
    ("Omelette with spinach", 380, ["eggs", "spinach", "cheese"]),
    ("Pancakes with honey", 450, ["flour", "milk", "eggs", "honey"]),
    ("Yoghurt parfait", 340, ["yoghurt", "oats", "berries"]),
    ("Boiled eggs with toast", 360, ["eggs", "bread", "tomato"]),
    ("Overnight oats", 330, ["oats", "milk", "banana"]),
    ("Cheese omelette", 400, ["eggs", "cheese"]),
]

_SNACKS = [
    ("Apple with peanut butter", 200, ["apple", "peanut_butter"]),
    ("Yoghurt cup", 150, ["yoghurt"]),
    ("Handful of nuts", 220, ["nuts"]),
    ("Banana with honey", 180, ["banana", "honey"]),
    ("Cheese and crackers", 230, ["cheese", "bread"]),
    ("Hummus with carrot sticks", 190, ["chickpeas", "carrot"]),
    ("Boiled egg and toast", 220, ["eggs", "bread"]),
    ("Greek yoghurt with honey", 200, ["yoghurt", "honey"]),
    ("Rice cakes with peanut butter", 210, ["rice", "peanut_butter"]),
    ("Trail mix", 250, ["nuts", "berries"]),
    ("Cottage cheese with berries", 180, ["cheese", "berries"]),
    ("Protein smoothie", 260, ["milk", "banana", "peanut_butter"]),
    ("Oat bar", 200, ["oats", "honey"]),
    ("Chicken skewers", 220, ["chicken"]),
    ("Turkey slices with cheese", 210, ["turkey", "cheese"]),
    ("Tuna on crackers", 230, ["tuna", "bread"]),
    ("Fruit salad", 160, ["apple", "berries", "banana"]),
    ("Veggie sticks with hummus", 170, ["carrot", "zucchini", "chickpeas"]),
    ("Yoghurt with granola", 240, ["yoghurt", "granola"]),
    ("Popcorn", 150, ["corn"]),
]

_LUNCHES = [
    ("Chicken with rice", 750, ["chicken", "rice", "broccoli"]),
    ("Beef stir fry with rice", 800, ["beef", "rice", "pepper", "onion"]),
    ("Salmon with quinoa", 700, ["salmon", "quinoa", "spinach"]),
    ("Pasta with tomato sauce", 780, ["pasta", "tomato", "garlic", "cheese"]),
    ("Chickpea salad", 650, ["chickpeas", "lettuce", "tomato", "olive_oil"]),
    ("Turkey with potato", 720, ["turkey", "potato", "carrot"]),
    ("Tofu stir fry with rice", 680, ["tofu", "rice", "broccoli", "pepper"]),
    ("Pork with rice and beans", 800, ["pork", "rice", "beans"]),
    ("Shrimp pasta", 750, ["shrimp", "pasta", "garlic", "tomato"]),
    ("Lentil stew", 650, ["lentils", "carrot", "onion", "potato"]),
    ("Chicken fajitas", 720, ["chicken", "pepper", "onion", "tomato"]),
    ("Beef tacos", 780, ["beef", "tomato", "lettuce", "cheese"]),
    ("Tuna salad with quinoa", 620, ["tuna", "quinoa", "lettuce"]),
    ("Grilled chicken with vegetables", 700, ["chicken", "zucchini", "carrot", "broccoli"]),
    ("Rice and beans bowl", 750, ["rice", "beans", "corn", "avocado"]),
    ("Salmon with rice", 780, ["salmon", "rice", "spinach"]),
    ("Pasta with chicken", 800, ["pasta", "chicken", "tomato", "cheese"]),
    ("Vegetable curry with rice", 700, ["chickpeas", "rice", "carrot", "onion", "garlic"]),
]

_DINNERS = [
    ("Grilled chicken with broccoli", 550, ["chicken", "broccoli"]),
    ("Salmon with spinach", 580, ["salmon", "spinach"]),
    ("Beef stew", 650, ["beef", "carrot", "potato", "onion"]),
    ("Vegetable soup with lentils", 500, ["lentils", "carrot", "onion", "potato"]),
    ("Tofu with vegetables", 520, ["tofu", "broccoli", "pepper"]),
    ("Turkey meatballs with zucchini", 600, ["turkey", "zucchini", "tomato"]),
    ("Shrimp stir fry", 560, ["shrimp", "pepper", "onion", "broccoli"]),
    ("Chicken soup", 500, ["chicken", "carrot", "onion"]),
    ("Pork chops with vegetables", 620, ["pork", "zucchini", "carrot"]),
    ("Tuna steak with vegetables", 580, ["tuna", "spinach", "tomato"]),
    ("Chickpea curry", 600, ["chickpeas", "tomato", "onion", "garlic"]),
    ("Beef with mashed potato", 680, ["beef", "potato", "carrot"]),
    ("Grilled salmon with quinoa", 650, ["salmon", "quinoa"]),
    ("Lentil soup", 520, ["lentils", "tomato", "onion", "carrot"]),
    ("Rice with beans and vegetables", 600, ["rice", "beans", "pepper", "corn"]),
    ("Chicken with quinoa", 620, ["chicken", "quinoa", "broccoli"]),
    ("Turkey with rice", 600, ["turkey", "rice", "spinach"]),
    ("Vegetable stir fry with tofu", 540, ["tofu", "pepper", "zucchini", "carrot"]),
]


def _build() -> list[Dish]:
    dishes: list[Dish] = []
    next_id = 1
    for meal_type, rows in (
        (MealType.BREAKFAST, _BREAKFASTS),
        (MealType.SNACK, _SNACKS),
        (MealType.LUNCH, _LUNCHES),
        (MealType.DINNER, _DINNERS),
    ):
        for name, kcal, foods in rows:
            dishes.append(_dish(next_id, name, meal_type, kcal, foods))
            next_id += 1
    return dishes


REALISTIC_CATALOGUE: list[Dish] = _build()
