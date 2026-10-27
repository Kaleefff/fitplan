"""Diet plan generator (algorithms.md section 5; FR-P6, FR-P7).

Pure functions: the caller loads the food catalogue with allergens, the user's
allergens and excluded foods, and the daily targets of section 2; it stores the
returned draft and turns `InsufficientFoodsError` into 422 `insufficient_foods`.
"""

import math
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
from scipy.optimize import lsq_linear

from app.domain.constants import (
    DAY_TOLERANCES,
    DIET_ATTEMPTS,
    DIET_EXTRA_ATTEMPTS,
    DIET_MEAL_CANDIDATES,
    DIET_PLAN_DAYS,
    GOOD_MEAL_ERROR,
    GRAM_FIT_WEIGHTS,
    MEAL_ROLES,
    MEAL_SLOTS,
    SNACK_OPTIONAL_ROLE,
    DietRole,
    DietType,
    Goal,
    MealType,
)
from app.domain.rounding import round_half_up
from app.domain.training import goal_label

Macros = tuple[float, float, float, float]  # kcal, protein g, fat g, carbs g


@dataclass(frozen=True)
class FoodInfo:
    id: int
    diet_role: DietRole
    suitable_meal_types: frozenset[MealType]
    per_100g: Macros
    min_portion_g: int
    max_portion_g: int
    portion_step_g: int
    is_active: bool = True
    is_vegetarian: bool = False
    is_vegan: bool = False
    allergen_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class MealItem:
    food_item_id: int
    grams: float


@dataclass(frozen=True)
class PlannedMeal:
    day_index: int  # 1-7
    meal_order: int
    meal_type: MealType
    planned_time: str
    items: tuple[MealItem, ...]
    kcal: int
    protein: float  # one decimal
    fat: float
    carbs: float


@dataclass(frozen=True)
class GeneratedDietPlan:
    name: str
    meals: tuple[PlannedMeal, ...]


@dataclass
class InsufficientFoodsError(Exception):
    """5.5: 422 `insufficient_foods`; `details` follow the Error model."""

    details: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 5.2 eligibility


def food_is_eligible(
    food: FoodInfo,
    meal_type: MealType,
    diet_type: DietType,
    allergen_ids: frozenset[int],
    excluded_food_ids: frozenset[int],
) -> bool:
    return (
        food.is_active
        and meal_type in food.suitable_meal_types
        and (diet_type != DietType.VEGETARIAN or food.is_vegetarian)
        and (diet_type != DietType.VEGAN or food.is_vegan)
        and not food.allergen_ids & allergen_ids
        and food.id not in excluded_food_ids
    )


# ---------------------------------------------------------------- 5.4 grams


def _relative_errors(actual: np.ndarray, target: np.ndarray) -> np.ndarray:
    return (actual - target) / np.maximum(target, 1e-9)


def _weighted_error(actual: np.ndarray, target: np.ndarray) -> float:
    return float(np.sum(np.array(GRAM_FIT_WEIGHTS) * _relative_errors(actual, target) ** 2))


def fit_grams(foods: list[FoodInfo], target: np.ndarray) -> tuple[list[float], np.ndarray]:
    """Bounded least squares over grams/100, rounded to each food's portion step."""
    per_100g = np.array([food.per_100g for food in foods], dtype=float).T  # 4 x items
    scale = np.sqrt(GRAM_FIT_WEIGHTS) / np.maximum(target, 1e-9)
    lower = np.array([food.min_portion_g for food in foods]) / 100
    upper = np.array([food.max_portion_g for food in foods]) / 100
    solution = lsq_linear(
        per_100g * scale[:, None],
        target * scale,
        bounds=(lower, np.maximum(upper, lower + 1e-9)),
    ).x
    grams = []
    for food, value in zip(foods, solution * 100, strict=True):
        step = food.portion_step_g
        rounded = math.floor(value / step + 0.5) * step  # half up to the step
        grams.append(float(min(max(rounded, food.min_portion_g), food.max_portion_g)))
    return grams, per_100g @ (np.array(grams) / 100)


# ---------------------------------------------------------------- 5.3 composition


@dataclass
class _Pools:
    """Eligible foods per (meal type, role slot), sorted by id."""

    by_slot: dict[tuple[MealType, tuple[DietRole, ...]], list[FoodInfo]]
    dishes: dict[MealType, list[FoodInfo]]
    snack_fat: list[FoodInfo]


def _pools(foods, meal_types, diet_type, allergen_ids, excluded_food_ids) -> _Pools:
    def eligible(meal_type: MealType, roles) -> list[FoodInfo]:
        return sorted(
            (
                f
                for f in foods
                if f.diet_role in roles
                and food_is_eligible(f, meal_type, diet_type, allergen_ids, excluded_food_ids)
            ),
            key=lambda f: f.id,
        )

    return _Pools(
        by_slot={(m, roles): eligible(m, roles) for m in meal_types for roles in MEAL_ROLES[m]},
        dishes={m: eligible(m, (DietRole.DISH,)) for m in (MealType.LUNCH, MealType.DINNER)},
        snack_fat=eligible(MealType.SNACK, (SNACK_OPTIONAL_ROLE,)),
    )


def _unfillable(pools: _Pools, meal_types) -> list[dict]:
    details, seen = [], set()
    for meal_type in meal_types:
        dishes = pools.dishes.get(meal_type, [])
        for roles in MEAL_ROLES[meal_type]:
            if pools.by_slot[(meal_type, roles)]:
                continue
            if dishes and roles[0] in (DietRole.PROTEIN, DietRole.CARB):
                continue  # a dish replaces protein + carb
            for role in roles:
                if (meal_type, role) not in seen:
                    seen.add((meal_type, role))
                    details.append(
                        {
                            "field": "food",
                            "code": "no_eligible_food",
                            "meal_type": meal_type.value,
                            "role": role.value,
                        }
                    )
    return details


def _rotate(pool: list[FoodInfo], index: int, previous: int | None) -> FoodInfo:
    food = pool[index % len(pool)]
    if food.id == previous and len(pool) >= 2:
        food = pool[(index + 1) % len(pool)]
    return food


def _compose(
    pools: _Pools,
    meal_type: MealType,
    day: int,
    slot: int,
    offset: int,
    allow_dish: bool,
    previous_day: dict,
    chosen_today: dict,
) -> list[list[FoodInfo]]:
    """The item lists to try for one meal: index (d - 1 + 2i + offset) mod n per role.

    Lunch and dinner: the protein slot also offers dishes (stage 1); a dish takes the
    carb's place. Snack: with and without the optional fat (questions.md, B-12).
    """
    index = day - 1 + 2 * slot + offset
    items: list[FoodInfo] = []
    dish_chosen = False
    for roles in MEAL_ROLES[meal_type]:
        key = (slot, roles)
        pool = pools.by_slot[(meal_type, roles)]
        if roles == (DietRole.PROTEIN,) and meal_type in pools.dishes:
            dishes = pools.dishes[meal_type] if allow_dish else []
            if not pools.by_slot[(meal_type, (DietRole.CARB,))]:
                pool = dishes  # nothing to pair the protein with
            else:
                pool = sorted(pool + dishes, key=lambda f: f.id)
        if roles == (DietRole.CARB,) and dish_chosen:
            continue
        if not pool:
            return []  # stage 2 without dishes cannot fill this meal
        food = _rotate(pool, index, previous_day.get(key))
        chosen_today[key] = food.id
        dish_chosen = dish_chosen or food.diet_role == DietRole.DISH
        items.append(food)
    if meal_type == MealType.SNACK and pools.snack_fat:
        key = (slot, (SNACK_OPTIONAL_ROLE,))
        fat = _rotate(pools.snack_fat, index, previous_day.get(key))
        chosen_today[key] = fat.id
        return [items, [*items, fat]]
    return [items]


# ---------------------------------------------------------------- 5.5 search


@dataclass
class _Meal:
    foods: list[FoodInfo]
    grams: list[float]
    nutrition: np.ndarray
    chosen: dict


def _best_meal(options: list[list[FoodInfo]], target: np.ndarray, chosen: dict) -> _Meal | None:
    best = None
    for foods in options:
        grams, nutrition = fit_grams(foods, target)
        if best is None or _weighted_error(nutrition, target) < _weighted_error(
            best.nutrition, target
        ):
            best = _Meal(foods, grams, nutrition, chosen)
    return best


def _day_ok(meals: list[_Meal], daily: np.ndarray) -> bool:
    totals = sum(meal.nutrition for meal in meals)
    return bool(np.all(np.abs(_relative_errors(totals, daily)) <= np.array(DAY_TOLERANCES)))


def _stage_one(pools, slots, day, daily, previous_day) -> list[_Meal] | None:
    for attempt in range(DIET_ATTEMPTS):
        meals = []
        for slot, (meal_type, share, _) in enumerate(slots):
            chosen: dict = {}
            options = _compose(pools, meal_type, day, slot, attempt, True, previous_day, chosen)
            meal = _best_meal(options, daily * share, chosen)
            if meal is None:
                break
            meals.append(meal)
        if len(meals) == len(slots) and _day_ok(meals, daily):
            return meals
    return None


def _stage_two(pools, slots, day, daily, previous_day) -> list[_Meal] | None:
    for attempt in range(DIET_EXTRA_ATTEMPTS):
        meals: list[_Meal] = []
        for slot, (meal_type, share, _) in enumerate(slots):
            built = sum((m.nutrition for m in meals), np.zeros(4))
            shares_left = sum(s for _, s, _ in slots[slot:])
            # each meal aims at its share of what the day still misses
            target = np.maximum(daily - built, daily * 0.01) * share / shares_left
            best = None
            first = attempt * DIET_MEAL_CANDIDATES
            for offset in range(first, first + DIET_MEAL_CANDIDATES):
                chosen: dict = {}
                options = _compose(pools, meal_type, day, slot, offset, False, previous_day, chosen)
                meal = _best_meal(options, target, chosen)
                if meal is None:
                    continue
                if best is None or _weighted_error(meal.nutrition, target) < _weighted_error(
                    best.nutrition, target
                ):
                    best = meal
                if np.all(np.abs(_relative_errors(meal.nutrition, target)) <= GOOD_MEAL_ERROR):
                    break
            if best is None:
                break
            meals.append(best)
        if len(meals) == len(slots) and _day_ok(meals, daily):
            return meals
    return None


def diet_plan_name(goal: Goal, diet_type: DietType, meals_per_day: int) -> str:
    """5.5: "<Goal>[ <diet type>] diet, <n> meals"; omnivore is not named."""
    kind = "" if diet_type == DietType.OMNIVORE else f" {diet_type.value}"
    return f"{goal_label(goal)}{kind} diet, {meals_per_day} meals"


def generate_diet_plan(
    goal: Goal,
    daily_targets: Macros,
    meals_per_day: int,
    diet_type: DietType,
    allergen_ids: frozenset[int],
    excluded_food_ids: frozenset[int],
    foods: list[FoodInfo],
) -> GeneratedDietPlan:
    slots = [(m, share, time) for m, share, time in MEAL_SLOTS[meals_per_day]]
    meal_types = list(dict.fromkeys(m for m, _, _ in slots))
    pools = _pools(foods, meal_types, diet_type, allergen_ids, excluded_food_ids)
    if missing := _unfillable(pools, meal_types):
        raise InsufficientFoodsError(missing)

    daily = np.array(daily_targets, dtype=float)
    previous_day: dict = {}
    planned: list[PlannedMeal] = []
    for day in range(1, DIET_PLAN_DAYS + 1):
        meals = _stage_one(pools, slots, day, daily, previous_day) or _stage_two(
            pools, slots, day, daily, previous_day
        )
        if meals is None:
            raise InsufficientFoodsError([{"code": "targets_not_reachable"}])
        previous_day = {key: food for meal in meals for key, food in meal.chosen.items()}
        for order, ((meal_type, _, time), meal) in enumerate(zip(slots, meals, strict=True), 1):
            kcal, protein, fat, carbs = (float(v) for v in meal.nutrition)
            planned.append(
                PlannedMeal(
                    day_index=day,
                    meal_order=order,
                    meal_type=meal_type,
                    planned_time=time,
                    items=tuple(
                        MealItem(f.id, g) for f, g in zip(meal.foods, meal.grams, strict=True)
                    ),
                    kcal=int(round_half_up(_decimal(kcal))),
                    protein=float(round_half_up(_decimal(protein), 1)),
                    fat=float(round_half_up(_decimal(fat), 1)),
                    carbs=float(round_half_up(_decimal(carbs), 1)),
                )
            )
    return GeneratedDietPlan(diet_plan_name(goal, diet_type, meals_per_day), tuple(planned))


def _decimal(value: float) -> Decimal:
    return Decimal(repr(value))
