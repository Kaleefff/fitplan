"""Diet plans and the food catalogue: `app.services.diet_plans.DietPlanStore` (B-12)."""

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, time
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import DietType as DbDietType
from app.db.enums import GoalType, PlanStatus
from app.db.enums import MealType as DbMealType
from app.db.models import (
    AppUser,
    DietPlan,
    FoodItem,
    FoodItemAllergen,
    Meal,
    MealFoodItem,
    UserAllergen,
    UserExcludedFood,
)
from app.db.repositories.profile_data import SqlProfileStore
from app.domain.constants import DietRole, MealType
from app.domain.diet import FoodInfo, GeneratedDietPlan
from app.domain.nutrition import NutritionTargets
from app.services.diet_plans import DietPlanView, DietRequest, MealItemView, MealView
from app.services.profile import ProfileView


class SqlDietPlanStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_user(self, user_id: int) -> None:
        await self._session.execute(
            select(AppUser.id).where(AppUser.id == user_id).with_for_update()
        )

    async def profile(self, user_id: int) -> ProfileView | None:
        return await SqlProfileStore(self._session).get_profile(user_id)

    async def foods(self) -> list[FoodInfo]:
        allergens = defaultdict(set)
        for food_id, allergen_id in await self._session.execute(
            select(FoodItemAllergen.food_item_id, FoodItemAllergen.allergen_id)
        ):
            allergens[food_id].add(allergen_id)
        rows = await self._session.scalars(select(FoodItem).order_by(FoodItem.id))
        return [
            FoodInfo(
                id=f.id,
                diet_role=DietRole(f.diet_role.value),
                suitable_meal_types=frozenset(MealType(m.value) for m in f.suitable_meal_types),
                per_100g=(
                    float(f.cals_per_100g),
                    float(f.protein_per_100g),
                    float(f.fat_per_100g),
                    float(f.carbs_per_100g),
                ),
                min_portion_g=float(f.min_portion_g),
                max_portion_g=float(f.max_portion_g),
                portion_step_g=float(f.portion_step_g),
                is_active=f.is_active,
                is_vegetarian=f.is_vegetarian,
                is_vegan=f.is_vegan,
                allergen_ids=frozenset(allergens[f.id]),
            )
            for f in rows
        ]

    async def user_allergens(self, user_id: int) -> frozenset[int]:
        rows = await self._session.scalars(
            select(UserAllergen.allergen_id).where(UserAllergen.user_id == user_id)
        )
        return frozenset(rows)

    async def excluded_foods(self, user_id: int) -> frozenset[int]:
        rows = await self._session.scalars(
            select(UserExcludedFood.food_item_id).where(UserExcludedFood.user_id == user_id)
        )
        return frozenset(rows)

    async def replace_draft(
        self,
        user_id: int,
        request: DietRequest,
        goal: str,
        targets: NutritionTargets,
        plan: GeneratedDietPlan,
    ) -> int:
        await self._session.execute(
            delete(DietPlan).where(DietPlan.user_id == user_id, DietPlan.status == PlanStatus.DRAFT)
        )
        row = DietPlan(
            user_id=user_id,
            name=plan.name,
            goal=GoalType(goal),
            diet_type=DbDietType(request.diet_type.value),
            meals_per_day=request.meals_per_day,
            daily_cal_goal=targets.target_kcal,
            protein_goal=targets.protein_g,
            fat_goal=targets.fat_g,
            carbs_goal=targets.carbs_g,
            status=PlanStatus.DRAFT,
            dietary_restrictions=request.dietary_restrictions,
        )
        self._session.add(row)
        await self._session.flush()
        for planned in plan.meals:
            meal = Meal(
                diet_plan_id=row.id,
                day_index=planned.day_index,
                meal_type=DbMealType(planned.meal_type.value),
                meal_order=planned.meal_order,
                planned_time=time.fromisoformat(planned.planned_time),
                planned_cals=planned.kcal,
                planned_protein=Decimal(str(planned.protein)),
                planned_fat=Decimal(str(planned.fat)),
                planned_carbs=Decimal(str(planned.carbs)),
            )
            self._session.add(meal)
            await self._session.flush()
            self._session.add_all(
                MealFoodItem(
                    meal_id=meal.id, food_item_id=item.food_item_id, grams=Decimal(str(item.grams))
                )
                for item in planned.items
            )
        await self._session.flush()
        return row.id

    async def get_plan(self, user_id: int, plan_id: int) -> DietPlanView | None:
        plan = await self._session.scalar(
            select(DietPlan).where(DietPlan.id == plan_id, DietPlan.user_id == user_id)
        )
        return None if plan is None else await self._view(plan)

    async def get_active(self, user_id: int) -> DietPlanView | None:
        plan = await self._session.scalar(
            select(DietPlan).where(
                DietPlan.user_id == user_id, DietPlan.status == PlanStatus.ACTIVE
            )
        )
        return None if plan is None else await self._view(plan)

    async def activate(self, user_id: int, plan_id: int, start: date, end: date) -> None:
        # archive first: at most one active plan per user
        await self._session.execute(
            update(DietPlan)
            .where(DietPlan.user_id == user_id, DietPlan.status == PlanStatus.ACTIVE)
            .values(status=PlanStatus.ARCHIVED)
        )
        await self._session.execute(
            update(DietPlan)
            .where(DietPlan.id == plan_id)
            .values(status=PlanStatus.ACTIVE, start_date=start, end_date=end)
        )

    async def _view(self, plan: DietPlan) -> DietPlanView:
        await self._session.refresh(plan)
        meals = (
            await self._session.scalars(
                select(Meal)
                .where(Meal.diet_plan_id == plan.id)
                .order_by(Meal.day_index, Meal.meal_order)
            )
        ).all()
        items = defaultdict(list)
        for meal_id, food_id, name, grams in await self._session.execute(
            select(
                MealFoodItem.meal_id, MealFoodItem.food_item_id, FoodItem.name, MealFoodItem.grams
            )
            .join(FoodItem, FoodItem.id == MealFoodItem.food_item_id)
            .where(MealFoodItem.meal_id.in_([m.id for m in meals]))
        ):
            items[meal_id].append(MealItemView(food_id, name, grams))
        return DietPlanView(
            id=plan.id,
            name=plan.name,
            goal=plan.goal.value,
            diet_type=plan.diet_type.value,
            meals_per_day=plan.meals_per_day,
            generated_at=plan.generated_at,
            start_date=plan.start_date,
            end_date=plan.end_date,
            daily_cal_goal=plan.daily_cal_goal,
            protein_goal=plan.protein_goal,
            fat_goal=plan.fat_goal,
            carbs_goal=plan.carbs_goal,
            status=plan.status.value,
            dietary_restrictions=plan.dietary_restrictions,
            meals=tuple(
                MealView(
                    id=m.id,
                    day_index=m.day_index,
                    meal_type=m.meal_type.value,
                    meal_order=m.meal_order,
                    planned_time=m.planned_time,
                    planned_cals=m.planned_cals,
                    planned_protein=m.planned_protein,
                    planned_fat=m.planned_fat,
                    planned_carbs=m.planned_carbs,
                    items=tuple(items[m.id]),
                )
                for m in meals
            ),
        )


class SqlDietPlanUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlDietPlanStore]:
        async with self._sessions.begin() as session:
            yield SqlDietPlanStore(session)
