"""Diet plan generator, algorithms.md section 5 (B-12).

The catalogue below is a test fixture with USDA-like values per 100 g; the real
food seed is DB-04.
"""

from decimal import Decimal as D

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.constants import (
    DAY_TOLERANCES,
    MEAL_SLOTS,
    DietRole,
    DietType,
    Goal,
    MealType,
    Sex,
)
from app.domain.diet import (
    FoodInfo,
    InsufficientFoodsError,
    diet_plan_name,
    fit_grams,
    food_is_eligible,
    generate_diet_plan,
)
from app.domain.nutrition import calculate_targets

B, L, DN, S = MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK
MILK, PEANUT, GLUTEN, FISH, EGG, SOY, NUTS = 1, 2, 3, 4, 5, 6, 7
OMNI, VEGETARIAN, VEGAN = "omni", "vegetarian", "vegan"


def food(id_, role, meals, macros, portion, kind=VEGAN, allergens=()):
    low, high, step = portion
    return FoodInfo(
        id=id_,
        diet_role=role,
        suitable_meal_types=frozenset(meals),
        per_100g=macros,
        min_portion_g=low,
        max_portion_g=high,
        portion_step_g=step,
        is_vegetarian=kind in (VEGETARIAN, VEGAN),
        is_vegan=kind == VEGAN,
        allergen_ids=frozenset(allergens),
    )


P, C, V, F, DA, FT, DI = (
    DietRole.PROTEIN,
    DietRole.CARB,
    DietRole.VEGETABLE,
    DietRole.FRUIT,
    DietRole.DAIRY,
    DietRole.FAT,
    DietRole.DISH,
)

# id, role, meal types, (kcal, protein, fat, carbs) per 100 g, (min, max, step) g
CATALOGUE = [
    food(1, P, (L, DN), (165, 31, 3.6, 0), (50, 300, 10), OMNI),  # chicken breast
    food(2, P, (L, DN), (208, 20, 13, 0), (50, 250, 10), OMNI, (FISH,)),  # salmon
    food(3, P, (B, L, DN), (143, 12.6, 9.5, 0.7), (50, 200, 10), VEGETARIAN, (EGG,)),  # eggs
    food(4, P, (B, L, DN), (144, 17.3, 8.7, 2.8), (50, 300, 10), VEGAN, (SOY,)),  # tofu
    food(5, P, (L, DN), (135, 30, 1, 0), (50, 300, 10), OMNI),  # turkey
    food(6, P, (L, DN), (192, 20, 11, 7.6), (50, 250, 10), VEGAN, (SOY,)),  # tempeh
    food(7, P, (B, L, DN), (370, 75, 1.9, 14), (30, 150, 10), VEGAN, (GLUTEN,)),  # seitan
    food(8, P, (L, DN), (116, 9, 0.4, 20), (50, 300, 10)),  # lentils
    food(20, DA, (B, S), (59, 10, 0.4, 3.6), (100, 400, 50), VEGETARIAN, (MILK,)),  # greek yogurt
    food(21, DA, (B, S), (63, 11, 0.2, 4), (100, 400, 50), VEGETARIAN, (MILK,)),  # skyr
    food(22, DA, (B, S), (98, 11, 4.3, 3.4), (100, 300, 50), VEGETARIAN, (MILK,)),  # cottage
    food(23, DA, (B, S), (90, 9, 2.5, 7), (100, 400, 50), VEGAN, (SOY,)),  # soy protein pudding
    food(24, DA, (B, S), (33, 3.3, 1.8, 0.6), (100, 500, 50), VEGAN, (SOY,)),  # soy milk
    food(30, C, (B,), (389, 16.9, 6.9, 66), (30, 150, 10), VEGAN, (GLUTEN,)),  # oats
    food(31, C, (L, DN), (130, 2.7, 0.3, 28), (50, 500, 10)),  # rice (endurance needs 500 g)
    food(32, C, (L, DN), (87, 1.9, 0.1, 20), (100, 500, 50)),  # potatoes
    food(33, C, (B, L, DN), (247, 13, 3.4, 41), (30, 150, 10), VEGAN, (GLUTEN,)),  # bread
    food(34, C, (L, DN), (158, 5.8, 0.9, 31), (50, 500, 10), VEGAN, (GLUTEN,)),  # pasta
    food(35, C, (L, DN), (92, 3.4, 0.6, 20), (50, 400, 10)),  # buckwheat
    food(40, V, (L, DN), (34, 2.8, 0.4, 7), (50, 300, 50)),  # broccoli
    food(41, V, (L, DN), (15, 1.2, 0.2, 2.9), (50, 300, 50)),  # salad
    food(42, V, (L, DN), (41, 0.9, 0.2, 10), (50, 300, 50)),  # carrots
    food(43, V, (L, DN), (23, 2.9, 0.4, 3.6), (50, 300, 50)),  # spinach
    food(50, F, (B, S), (89, 1.1, 0.3, 23), (50, 250, 10)),  # banana
    food(51, F, (B, S), (52, 0.3, 0.2, 14), (50, 300, 10)),  # apple
    food(52, F, (B, S), (57, 0.7, 0.3, 14), (50, 250, 10)),  # berries
    food(60, FT, (L, DN), (884, 0, 100, 0), (5, 30, 5)),  # olive oil
    food(61, FT, (B, S), (588, 25, 50, 20), (10, 40, 5), VEGAN, (PEANUT,)),  # peanut butter
    food(62, FT, (B, S), (579, 21, 50, 22), (10, 50, 5), VEGAN, (NUTS,)),  # almonds
    food(63, FT, (B, L, DN), (160, 2, 15, 9), (30, 150, 10)),  # avocado
    # high-carb for endurance (476 g carbs a day) and high-protein vegan (33 % of kcal)
    food(9, P, (B, L, DN), (335, 80, 3, 7), (20, 60, 10), VEGAN, (SOY,)),  # soy protein isolate
    food(25, DA, (B, S), (60, 10, 1.5, 3), (100, 400, 50), VEGAN, (SOY,)),  # soy protein yogurt
    food(36, C, (B, L, DN), (257, 10, 1.6, 50), (50, 200, 10), VEGAN, (GLUTEN,)),  # bagel
    food(53, F, (B, S), (277, 1.8, 0.2, 75), (20, 100, 10)),  # dates
    food(70, DI, (L, DN), (150, 10, 5, 16), (200, 500, 50), OMNI),  # chicken curry with rice
    food(71, DI, (L, DN), (110, 6, 3, 15), (200, 500, 50)),  # vegan chili
]
BY_ID = {f.id: f for f in CATALOGUE}

PROFILES = [
    (Sex.MALE, D("80"), D("180"), 25, D("1.55")),
    (Sex.FEMALE, D("60"), D("165"), 30, D("1.375")),
]


def targets(profile, goal) -> tuple[float, float, float, float]:
    t = calculate_targets(*profile, goal)
    return float(t.target_kcal), float(t.protein_g), float(t.fat_g), float(t.carbs_g)


def day_totals(plan, day) -> np.ndarray:
    total = np.zeros(4)
    for meal in plan.meals:
        if meal.day_index == day:
            for item in meal.items:
                total += np.array(BY_ID[item.food_item_id].per_100g) * item.grams / 100
    return total


def generate(goal=Goal.MAINTENANCE, profile=PROFILES[0], meals=4, diet=DietType.OMNIVORE, **kw):
    return generate_diet_plan(
        goal,
        targets(profile, goal),
        meals,
        diet,
        kw.get("allergens", frozenset()),
        kw.get("excluded", frozenset()),
        kw.get("foods", CATALOGUE),
    )


# ---------------------------------------------------------------- 5.2, 5.4, names


def test_eligibility():
    yogurt = BY_ID[20]
    assert food_is_eligible(yogurt, B, DietType.VEGETARIAN, frozenset(), frozenset())
    assert not food_is_eligible(yogurt, L, DietType.OMNIVORE, frozenset(), frozenset())
    assert not food_is_eligible(yogurt, B, DietType.VEGAN, frozenset(), frozenset())
    assert not food_is_eligible(yogurt, B, DietType.OMNIVORE, frozenset({MILK}), frozenset())
    assert not food_is_eligible(yogurt, B, DietType.OMNIVORE, frozenset(), frozenset({20}))
    inactive = FoodInfo(99, F, frozenset({B}), (50, 1, 0, 12), 50, 100, 10, is_active=False)
    assert not food_is_eligible(inactive, B, DietType.OMNIVORE, frozenset(), frozenset())


def test_grams_respect_bounds_and_steps():
    foods = [BY_ID[1], BY_ID[31], BY_ID[40], BY_ID[60]]
    grams, nutrition = fit_grams(foods, np.array([700.0, 45.0, 20.0, 80.0]))
    for item, g in zip(foods, grams, strict=True):
        assert item.min_portion_g <= g <= item.max_portion_g
        assert g % item.portion_step_g == 0
    assert abs(nutrition[0] - 700) / 700 < 0.10


def test_names():
    assert diet_plan_name(Goal.WEIGHT_LOSS, DietType.OMNIVORE, 3) == "Weight loss diet, 3 meals"
    assert diet_plan_name(Goal.MUSCLE_GAIN, DietType.VEGAN, 5) == "Muscle gain vegan diet, 5 meals"


# ---------------------------------------------------------------- 5.1, 5.3 shape


def test_seven_days_with_the_slots_of_the_table():
    plan = generate(meals=5)

    assert len(plan.meals) == 7 * 5
    day_one = [m for m in plan.meals if m.day_index == 1]
    assert [(m.meal_order, m.meal_type, m.planned_time) for m in day_one] == [
        (1, B, "08:00"),
        (2, S, "10:30"),
        (3, L, "13:30"),
        (4, S, "16:30"),
        (5, DN, "19:00"),
    ]
    breakfast = day_one[0]
    roles = [BY_ID[i.food_item_id].diet_role for i in breakfast.items]
    assert roles[0] in (P, DA) and roles[1:] == [C, F, FT]


def test_meals_rotate_from_day_to_day():
    plan = generate(meals=3)
    lunches = [m.items for m in plan.meals if m.meal_type == L]
    assert len({tuple(i.food_item_id for i in items) for items in lunches}) > 1


# ---------------------------------------------------------------- 5.5 Done of B-12


@pytest.mark.parametrize("profile", PROFILES, ids=["male-80kg", "female-60kg"])
@pytest.mark.parametrize("meals", [3, 4, 5])
@pytest.mark.parametrize("diet", list(DietType))
@pytest.mark.parametrize("goal", list(Goal))
def test_every_goal_diet_and_meal_count_passes_the_tolerances(goal, diet, meals, profile):
    daily = np.array(targets(profile, goal))
    plan = generate(goal, profile, meals, diet)

    assert len(plan.meals) == 7 * meals
    for day in range(1, 8):
        errors = np.abs(day_totals(plan, day) - daily) / daily
        assert np.all(errors <= np.array(DAY_TOLERANCES)), (day, errors)
    for meal in plan.meals:
        for item in meal.items:
            chosen = BY_ID[item.food_item_id]
            assert meal.meal_type in chosen.suitable_meal_types
            assert chosen.min_portion_g <= item.grams <= chosen.max_portion_g
            assert item.grams % chosen.portion_step_g == 0
            assert diet != DietType.VEGAN or chosen.is_vegan
            assert diet != DietType.VEGETARIAN or chosen.is_vegetarian


@settings(max_examples=40, deadline=None)
@given(
    allergens=st.frozensets(st.sampled_from([MILK, PEANUT, GLUTEN, FISH, EGG, NUTS])),
    excluded=st.frozensets(st.sampled_from([1, 31, 40, 50, 60])),
    diet=st.sampled_from([DietType.OMNIVORE, DietType.VEGETARIAN]),
    meals=st.sampled_from([3, 4, 5]),
)
def test_allergens_and_excluded_foods_are_never_selected(allergens, excluded, diet, meals):
    try:
        plan = generate(meals=meals, diet=diet, allergens=allergens, excluded=excluded)
    except InsufficientFoodsError:
        return  # some combinations leave a role empty; that is reported, never ignored
    for meal in plan.meals:
        for item in meal.items:
            assert not BY_ID[item.food_item_id].allergen_ids & allergens
            assert item.food_item_id not in excluded


# ---------------------------------------------------------------- 5.5 failures


def test_an_empty_role_is_reported_per_meal_type():
    no_fruit = [f for f in CATALOGUE if f.diet_role != F]
    with pytest.raises(InsufficientFoodsError) as error:
        generate(meals=3, foods=no_fruit)
    assert error.value.details == [
        {"field": "food", "code": "no_eligible_food", "meal_type": "breakfast", "role": "fruit"}
    ]


def test_unreachable_targets():
    with pytest.raises(InsufficientFoodsError) as error:
        generate_diet_plan(
            Goal.MUSCLE_GAIN,
            (9000.0, 50.0, 30.0, 100.0),
            3,
            DietType.OMNIVORE,
            frozenset(),
            frozenset(),
            CATALOGUE,
        )
    assert error.value.details == [{"code": "targets_not_reachable"}]


def test_slot_shares_add_up():
    for slots in MEAL_SLOTS.values():
        assert sum(share for _, share, _ in slots) == pytest.approx(1.0)
