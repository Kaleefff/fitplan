"""Meal suggestions, algorithms.md section 10 (B-22)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.constants import DietRole, DietType, MealType
from app.domain.diet import FoodInfo
from app.domain.suggestions import (
    PlannedMealInfo,
    SuggestionKind,
    SuggestionStatus,
    food_grams,
    score,
    suggest_meals,
)

ALL_MEALS = frozenset(MealType)
OMNIVORE = DietType.OMNIVORE
NUTS = 7


def food(id_, per_100g=(200, 20, 10, 5), portions=(50, 300, 10), **flags) -> FoodInfo:
    return FoodInfo(
        id=id_,
        diet_role=flags.pop("role", DietRole.PROTEIN),
        suitable_meal_types=flags.pop("meal_types", ALL_MEALS),
        per_100g=per_100g,
        min_portion_g=portions[0],
        max_portion_g=portions[1],
        portion_step_g=portions[2],
        name=f"Food {id_}",
        **flags,
    )


def suggest(remaining, foods, daily=2000, planned=(), logged=(), **filters):
    return suggest_meals(
        remaining=remaining,
        daily_kcal=daily,
        planned_meals=list(planned),
        logged_meal_ids=frozenset(logged),
        foods=foods,
        meal_types=filters.get("meal_types", ALL_MEALS),
        diet_type=filters.get("diet_type", OMNIVORE),
        allergen_ids=frozenset(filters.get("allergens", ())),
        excluded_food_ids=frozenset(filters.get("excluded", ())),
    )


# ---------------------------------------------------------------- worked example


def test_one_food_worked_example():
    """remaining 700 kcal, P 50, F 20, C 80; daily 2000 -> ideal_kcal = min(700, 700).
    200 kcal/100 g -> 350 g, clamped to 300 g: 600 kcal, P 60, F 30, C 15.
    score = (10/50)² + (10/20)² + (-65/80)² = 0.04 + 0.25 + 0.66015625."""
    result = suggest((700, 50, 20, 80), [food(1)])

    assert result.status == SuggestionStatus.OK
    (only,) = result.suggestions
    assert (only.kind, only.food_item_id, only.meal_id, only.name) == (
        SuggestionKind.FOOD,
        1,
        None,
        "Food 1",
    )
    assert only.grams == 300
    assert only.nutrition == pytest.approx((600, 60, 30, 15))
    assert score(only.nutrition, (700, 50, 20, 80)) == pytest.approx(0.95015625)


def test_below_100_kcal_left_is_target_reached_and_remaining_is_at_least_zero():
    result = suggest((99.9, -10, 5, 0), [food(1)])

    assert result.status == SuggestionStatus.TARGET_REACHED
    assert result.suggestions == ()
    assert result.remaining == (99.9, 0, 5, 0)


# ---------------------------------------------------------------- step 2 grams


def test_grams_aim_at_35_percent_of_the_daily_target_rounded_half_up_to_the_step():
    # min(1000, 0.35 x 1000) = 350 kcal; 350 / 2 kcal per g = 175 g -> 180 g
    assert food_grams(food(1), 350) == 180
    assert food_grams(food(1), 10) == 50  # clamped to min
    assert food_grams(food(1, per_100g=(0, 0, 0, 0)), 350) == 300  # no energy: max


def test_the_ideal_kcal_is_capped_by_the_daily_share():
    (only,) = suggest((1000, 50, 30, 100), [food(1)], daily=1000).suggestions

    assert only.grams == 180


# ---------------------------------------------------------------- step 3 and 4


def test_candidates_above_remaining_kcal_times_1_05_are_dropped():
    heavy = food(1, per_100g=(500, 10, 40, 20), portions=(50, 300, 10))  # min 250 kcal
    edge = food(2, per_100g=(420, 10, 30, 20), portions=(50, 300, 10))  # min 210 kcal

    result = suggest((200, 20, 10, 20), [heavy, edge])

    assert [s.food_item_id for s in result.suggestions] == [2]  # 210 = 200 x 1.05 stays


def test_a_macro_with_nothing_left_is_not_scored():
    assert score((100, 30, 5, 10), (100, 30, 0, 10)) == 0
    assert score((100, 30, 5, 10), (100, 30, -4, 10)) == 0


def test_best_five_by_score_planned_meals_first_on_a_tie():
    foods = [food(i, per_100g=(200, 20 + i, 10, 5)) for i in range(1, 8)]
    twin = PlannedMealInfo(99, MealType.LUNCH, "Lunch: Food 1", ((1, 300),), (600, 63, 30, 15))
    result = suggest((700, 50, 20, 80), foods, planned=[twin])

    # food 1 (P 63) and the planned meal score the same; more protein scores worse
    assert [(s.kind, s.meal_id or s.food_item_id) for s in result.suggestions] == [
        (SuggestionKind.PLANNED_MEAL, 99),
        (SuggestionKind.FOOD, 1),
        (SuggestionKind.FOOD, 2),
        (SuggestionKind.FOOD, 3),
        (SuggestionKind.FOOD, 4),
    ]


# ---------------------------------------------------------------- step 1 candidates


def test_single_foods_follow_5_2():
    foods = [
        food(1, allergen_ids=frozenset({NUTS})),
        food(2),  # excluded by the user
        food(3, is_active=False),
        food(4, meal_types=frozenset({MealType.SNACK})),  # no snack in a 3-meal plan
        food(5, is_vegetarian=True),
        food(6),
    ]
    three_meals = frozenset({MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER})

    omnivore = suggest(
        (700, 50, 20, 80), foods, allergens=[NUTS], excluded=[2], meal_types=three_meals
    )
    vegetarian = suggest((700, 50, 20, 80), foods, diet_type=DietType.VEGETARIAN)

    assert {s.food_item_id for s in omnivore.suggestions} == {5, 6}
    assert {s.food_item_id for s in vegetarian.suggestions} == {5}


def test_planned_meals_not_logged_and_still_allowed():
    foods = [food(1), food(2, meal_types=frozenset({MealType.BREAKFAST})), food(3), food(4)]

    def meal(id_, items, meal_type=MealType.LUNCH):
        return PlannedMealInfo(id_, meal_type, f"Meal {id_}", items, (500, 40, 15, 50))

    planned = [
        meal(10, ((1, 100), (4, 150))),  # allowed: 250 g
        meal(11, ((1, 100),)),  # already logged
        meal(12, ((3, 100),)),  # food 3 now excluded
        meal(13, ((2, 100),)),  # food 2 not suitable for lunch
        meal(14, ((404, 100),)),  # food no longer in the catalogue
    ]

    result = suggest((700, 50, 20, 80), foods, planned=planned, logged=[11], excluded=[3])

    meals = [s for s in result.suggestions if s.kind == SuggestionKind.PLANNED_MEAL]
    assert [(s.meal_id, s.food_item_id, s.name, s.grams) for s in meals] == [
        (10, None, "Meal 10", 250)
    ]


# ---------------------------------------------------------------- property (Done of B-22)

foods_strategy = st.lists(
    st.builds(
        food,
        st.integers(1, 10_000),
        st.tuples(
            st.integers(0, 900),
            st.integers(0, 90),
            st.integers(0, 90),
            st.integers(0, 90),
        ),
        st.sampled_from([(5, 50, 5), (50, 300, 10), (100, 500, 50)]),
        allergen_ids=st.frozensets(st.integers(1, 10), max_size=2),
    ),
    max_size=30,
    unique_by=lambda f: f.id,
)
macro = st.floats(-500, 3000, allow_nan=False)


@settings(max_examples=300, deadline=None)
@given(
    foods=foods_strategy,
    remaining=st.tuples(macro, macro, macro, macro),
    daily=st.floats(1200, 4000),
    allergens=st.frozensets(st.integers(1, 10), max_size=3),
)
def test_never_above_remaining_kcal_and_never_an_allergen(foods, remaining, daily, allergens):
    by_id = {f.id: f for f in foods}
    result = suggest(remaining, foods, daily=daily, allergens=allergens)

    assert len(result.suggestions) <= 5
    assert all(value >= 0 for value in result.remaining)
    for suggestion in result.suggestions:
        assert suggestion.nutrition[0] <= remaining[0] * 1.05
        assert not by_id[suggestion.food_item_id].allergen_ids & allergens
