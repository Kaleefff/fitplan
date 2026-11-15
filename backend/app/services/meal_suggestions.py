"""Meal suggestions for the rest of a day (B-22; FR-N5, algorithms.md section 10)."""

from datetime import date

from app.core.errors import AppError, ErrorCode
from app.domain.constants import DIET_PLAN_DAYS, MEAL_SLOTS, DietType, MealType
from app.domain.suggestions import PlannedMealInfo, Suggestions, suggest_meals
from app.services.diet_plans import DietPlanUnitOfWork, DietPlanView, MealView
from app.services.nutrition_logs import NutritionLogUnitOfWork


def plan_day(plan: DietPlanView, day: date) -> int:
    """5.1: the plan repeats from `start_date`; day = ((date - start) mod 7) + 1."""
    start = plan.start_date or day
    return (day - start).days % DIET_PLAN_DAYS + 1


def _meal_name(meal: MealView) -> str:
    """ "Lunch: Chicken breast, Rice" (questions.md, B-22)."""
    foods = ", ".join(item.name for item in meal.items)
    return f"{meal.meal_type.capitalize()}: {foods}"


def _planned(meal: MealView) -> PlannedMealInfo:
    return PlannedMealInfo(
        id=meal.id,
        meal_type=MealType(meal.meal_type),
        name=_meal_name(meal),
        items=tuple((item.food_item_id, float(item.grams)) for item in meal.items),
        nutrition=(
            float(meal.planned_cals),
            float(meal.planned_protein),
            float(meal.planned_fat),
            float(meal.planned_carbs),
        ),
    )


class MealSuggestionService:
    def __init__(
        self, diet_plans: DietPlanUnitOfWork, nutrition_logs: NutritionLogUnitOfWork
    ) -> None:
        self._diet_plans = diet_plans
        self._nutrition_logs = nutrition_logs

    async def suggestions(self, user_id: int, day: date) -> Suggestions:
        """404 without an active diet plan; `day` is today in the user's time zone."""
        async with self._diet_plans() as store:
            plan = await store.get_active(user_id)
            if plan is None:
                raise AppError(404, ErrorCode.NOT_FOUND, "No active diet plan")
            foods = await store.foods()
            allergens = await store.user_allergens(user_id)
            excluded = await store.excluded_foods(user_id)
        async with self._nutrition_logs() as logs:
            summary = await logs.daily_summary(user_id, day)

        totals = summary.totals
        remaining = (
            float(plan.daily_cal_goal - totals.kcal),
            float(plan.protein_goal - totals.protein),
            float(plan.fat_goal - totals.fat),
            float(plan.carbs_goal - totals.carbs),
        )
        today = plan_day(plan, day)
        return suggest_meals(
            remaining=remaining,
            daily_kcal=float(plan.daily_cal_goal),
            planned_meals=[_planned(m) for m in plan.meals if m.day_index == today],
            logged_meal_ids=frozenset(
                log.planned_meal_id for log in summary.logs if log.planned_meal_id is not None
            ),
            foods=foods,
            meal_types=frozenset(slot[0] for slot in MEAL_SLOTS[plan.meals_per_day]),
            diet_type=DietType(plan.diet_type),
            allergen_ids=allergens,
            excluded_food_ids=excluded,
        )
