"""Meal suggestions (algorithms.md section 10; FR-N5).

Pure functions: the caller loads the active diet plan, today's planned meals, the ids
of the planned meals already logged today, the food catalogue, the user's allergens
and excluded foods, and what is left of today's targets.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

from app.domain.constants import (
    SUGGESTION_COUNT,
    SUGGESTION_IDEAL_SHARE,
    SUGGESTION_KCAL_MARGIN,
    SUGGESTION_MIN_REMAINING_KCAL,
    DietType,
    MealType,
)
from app.domain.diet import FoodInfo, Macros, food_is_eligible


class SuggestionStatus(StrEnum):
    OK = "ok"
    TARGET_REACHED = "target_reached"


class SuggestionKind(StrEnum):
    FOOD = "food"
    PLANNED_MEAL = "planned_meal"


@dataclass(frozen=True)
class PlannedMealInfo:
    id: int
    meal_type: MealType
    name: str
    items: tuple[tuple[int, float], ...]  # (food_item_id, grams)
    nutrition: Macros  # the meal's planned kcal and macros


@dataclass(frozen=True)
class Suggestion:
    kind: SuggestionKind
    food_item_id: int | None
    meal_id: int | None
    name: str
    grams: float
    nutrition: Macros


@dataclass(frozen=True)
class Suggestions:
    status: SuggestionStatus
    remaining: Macros  # never below 0
    suggestions: tuple[Suggestion, ...]


def food_grams(food: FoodInfo, ideal_kcal: float) -> float:
    """Step 2: clamp(ideal_kcal / kcal per g, min, max), rounded half up to the step.

    A food without energy gets its largest portion (the limit of the formula).
    """
    kcal_per_g = food.per_100g[0] / 100
    grams = ideal_kcal / kcal_per_g if kcal_per_g > 0 else food.max_portion_g
    grams = min(max(grams, food.min_portion_g), food.max_portion_g)
    step = food.portion_step_g
    rounded = math.floor(grams / step + 0.5) * step
    return float(min(max(rounded, food.min_portion_g), food.max_portion_g))


def _scaled(food: FoodInfo, grams: float) -> Macros:
    kcal, protein, fat, carbs = (value * grams / 100 for value in food.per_100g)
    return kcal, protein, fat, carbs


def score(nutrition: Macros, ideal: Macros) -> float:
    """Step 4: Σ ((c_j - ideal_j) / ideal_j)² over protein, fat and carbs.

    A macro with nothing left (ideal ≤ 0) is left out (questions.md, B-22).
    """
    total = 0.0
    for value, target in zip(nutrition[1:], ideal[1:], strict=True):
        if target > 0:
            error = (value - target) / target
            total += error * error  # inf, not OverflowError, for a tiny ideal
    return total


def suggest_meals(
    remaining: Macros,
    daily_kcal: float,
    planned_meals: list[PlannedMealInfo],
    logged_meal_ids: frozenset[int],
    foods: list[FoodInfo],
    meal_types: frozenset[MealType],
    diet_type: DietType,
    allergen_ids: frozenset[int],
    excluded_food_ids: frozenset[int],
) -> Suggestions:
    """`remaining` = today's targets - today's logs (may be negative); `meal_types` are
    the slots of the active plan, a single food has to fit one of them (5.2)."""
    shown = tuple(max(value, 0.0) for value in remaining)
    remaining_kcal = remaining[0]
    if remaining_kcal < SUGGESTION_MIN_REMAINING_KCAL:
        return Suggestions(SuggestionStatus.TARGET_REACHED, shown, ())

    ideal_kcal = min(remaining_kcal, SUGGESTION_IDEAL_SHARE * daily_kcal)
    ideal = tuple(value * ideal_kcal / remaining_kcal for value in remaining)
    by_id = {food.id: food for food in foods}

    def allowed(food_id: int, meal_type: MealType) -> bool:
        food = by_id.get(food_id)
        return food is not None and food_is_eligible(
            food, meal_type, diet_type, allergen_ids, excluded_food_ids
        )

    candidates = [
        Suggestion(
            SuggestionKind.PLANNED_MEAL,
            None,
            meal.id,
            meal.name,
            sum(grams for _, grams in meal.items),
            meal.nutrition,
        )
        for meal in planned_meals
        if meal.id not in logged_meal_ids
        and all(allowed(food_id, meal.meal_type) for food_id, _ in meal.items)
    ]
    for food in foods:
        if any(allowed(food.id, meal_type) for meal_type in meal_types):
            grams = food_grams(food, ideal_kcal)
            candidates.append(
                Suggestion(
                    SuggestionKind.FOOD, food.id, None, food.name, grams, _scaled(food, grams)
                )
            )

    limit = remaining_kcal * SUGGESTION_KCAL_MARGIN
    kept = [c for c in candidates if c.nutrition[0] <= limit]
    # ties: planned meals first, then by id (questions.md, B-22)
    kept.sort(
        key=lambda c: (
            score(c.nutrition, ideal),
            c.kind != SuggestionKind.PLANNED_MEAL,
            c.meal_id or c.food_item_id or 0,
        )
    )
    return Suggestions(SuggestionStatus.OK, shown, tuple(kept[:SUGGESTION_COUNT]))
