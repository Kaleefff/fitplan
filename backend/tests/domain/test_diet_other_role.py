"""DB-04: foods with diet_role 'other' (sweets, drinks, sauces) are never planned
(algorithms.md 5.3), even when they fit every meal and are listed first."""

import pytest

from app.domain.constants import MEAL_ROLES, DietRole, DietType, Goal, MealType
from app.domain.diet import FoodInfo, InsufficientFoodsError
from tests.domain.test_diet import CATALOGUE, generate

EVERY_MEAL = frozenset(MealType)
# low ids sort first in every pool; values that would suit any target
OTHER_FOODS = [
    FoodInfo(
        id=i,
        diet_role=DietRole.OTHER,
        suitable_meal_types=EVERY_MEAL,
        per_100g=(250, 20, 10, 20),
        min_portion_g=10,
        max_portion_g=500,
        portion_step_g=10,
        is_vegetarian=True,
        is_vegan=True,
    )
    for i in (-2, -1)
]
OTHER_IDS = {f.id for f in OTHER_FOODS}


def test_other_is_not_a_role_of_any_meal() -> None:
    planned = {role for slots in MEAL_ROLES.values() for slot in slots for role in slot}
    assert DietRole.OTHER not in planned


@pytest.mark.parametrize("meals", [3, 4, 5])
@pytest.mark.parametrize("diet", list(DietType))
def test_other_foods_are_never_selected(meals: int, diet: DietType) -> None:
    plan = generate(Goal.MAINTENANCE, meals=meals, diet=diet, foods=OTHER_FOODS + CATALOGUE)
    chosen = {item.food_item_id for meal in plan.meals for item in meal.items}
    assert not chosen & OTHER_IDS


def test_other_foods_alone_fill_no_role() -> None:
    with pytest.raises(InsufficientFoodsError):
        generate(Goal.MAINTENANCE, meals=4, foods=OTHER_FOODS)
