"""Diet plans: generate a draft, read, accept (B-12; FR-P4 to FR-P7).

The plan comes from `app/domain/diet.py` (algorithms.md section 5) with the targets of
section 2 for the stored profile; this module loads the inputs and stores the result.
Generation and acceptance take the user's row lock.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from anyio import to_thread

from app.core.errors import AppError, ErrorCode
from app.domain.constants import PLAN_DURATION_DAYS, DietType
from app.domain.diet import FoodInfo, GeneratedDietPlan, InsufficientFoodsError, generate_diet_plan
from app.domain.nutrition import NutritionTargets, calculate_targets
from app.services.profile import ProfileView


@dataclass(frozen=True)
class DietRequest:
    meals_per_day: int
    diet_type: DietType
    dietary_restrictions: str | None


@dataclass(frozen=True)
class MealItemView:
    food_item_id: int
    name: str
    grams: Decimal


@dataclass(frozen=True)
class MealView:
    id: int
    day_index: int
    meal_type: str
    meal_order: int
    planned_time: time
    planned_cals: int
    planned_protein: Decimal
    planned_fat: Decimal
    planned_carbs: Decimal
    items: tuple[MealItemView, ...]


@dataclass(frozen=True)
class DietPlanView:
    id: int
    name: str
    goal: str
    diet_type: str
    meals_per_day: int
    generated_at: datetime
    start_date: date | None
    end_date: date | None
    daily_cal_goal: int
    protein_goal: Decimal
    fat_goal: Decimal
    carbs_goal: Decimal
    status: str
    dietary_restrictions: str | None
    meals: tuple[MealView, ...]


class DietPlanStore(Protocol):
    """Every call of one unit of work runs in the same transaction."""

    async def lock_user(self, user_id: int) -> None: ...

    async def profile(self, user_id: int) -> ProfileView | None: ...

    async def foods(self) -> list[FoodInfo]: ...

    async def user_allergens(self, user_id: int) -> frozenset[int]: ...

    async def excluded_foods(self, user_id: int) -> frozenset[int]: ...

    async def replace_draft(
        self,
        user_id: int,
        request: DietRequest,
        goal: str,
        targets: NutritionTargets,
        plan: GeneratedDietPlan,
    ) -> int: ...

    async def get_plan(self, user_id: int, plan_id: int) -> DietPlanView | None: ...

    async def get_active(self, user_id: int) -> DietPlanView | None: ...

    async def activate(self, user_id: int, plan_id: int, start: date, end: date) -> None: ...


DietPlanUnitOfWork = Callable[[], AbstractAsyncContextManager[DietPlanStore]]


class DietPlanService:
    def __init__(self, unit_of_work: DietPlanUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def generate(self, user_id: int, request: DietRequest) -> DietPlanView:
        """5.5: a new draft replaces the previous one; on 422 nothing is stored."""
        async with self._unit_of_work() as store:
            await store.lock_user(user_id)
            profile = await store.profile(user_id)
            if profile is None:
                raise AppError(404, ErrorCode.NOT_FOUND, "No profile yet: targets need one")
            targets = calculate_targets(
                profile.sex,
                profile.current_weight,
                Decimal(profile.height),
                profile.age,
                profile.activity_level_pal,
                profile.goal,
            )
            daily = (
                float(targets.target_kcal),
                float(targets.protein_g),
                float(targets.fat_g),
                float(targets.carbs_g),
            )
            foods = await store.foods()
            allergens = await store.user_allergens(user_id)
            excluded = await store.excluded_foods(user_id)
            try:
                # bounded least squares for 7 days of meals: off the event loop
                plan = await to_thread.run_sync(
                    lambda: generate_diet_plan(
                        profile.goal,
                        daily,
                        request.meals_per_day,
                        request.diet_type,
                        allergens,
                        excluded,
                        foods,
                    )
                )
            except InsufficientFoodsError as error:
                raise AppError(
                    422,
                    ErrorCode.INSUFFICIENT_FOODS,
                    "The diet plan cannot meet the targets with the eligible foods",
                    error.details,
                ) from None
            plan_id = await store.replace_draft(user_id, request, profile.goal.value, targets, plan)
            return await store.get_plan(user_id, plan_id)

    async def get(self, user_id: int, plan_id: int) -> DietPlanView:
        async with self._unit_of_work() as store:
            plan = await store.get_plan(user_id, plan_id)
        if plan is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
        return plan

    async def get_active(self, user_id: int) -> DietPlanView:
        async with self._unit_of_work() as store:
            plan = await store.get_active(user_id)
        if plan is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "No active diet plan")
        return plan

    async def accept(
        self, user_id: int, plan_id: int, start: date | None, timezone: str, now: datetime
    ) -> DietPlanView:
        """As 4.8: only a draft; archives the active plan; end = start + 56 days."""
        async with self._unit_of_work() as store:
            await store.lock_user(user_id)
            plan = await store.get_plan(user_id, plan_id)
            if plan is None:
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
            if plan.status != "draft":
                raise AppError(409, ErrorCode.CONFLICT, f"The plan is {plan.status}, not a draft")
            start = start or now.astimezone(ZoneInfo(timezone)).date()
            await store.activate(user_id, plan_id, start, start + timedelta(PLAN_DURATION_DAYS))
            return await store.get_plan(user_id, plan_id)
