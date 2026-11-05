from datetime import UTC, date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_current_user, get_diet_plan_service, get_user_repository
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.domain.constants import MEALS_PER_DAY_MAX, MEALS_PER_DAY_MIN, DietType, Goal, MealType
from app.services.auth import UserRepository
from app.services.diet_plans import DietPlanService, DietPlanView, DietRequest

router = APIRouter(prefix="/diet-plans", tags=["diet"])

INT_MAX = 2_147_483_647
PlanId = Annotated[int, Path(ge=1, le=INT_MAX)]


class GenerateDietPlanRequest(BaseModel):
    meals_per_day: Annotated[int, Field(ge=MEALS_PER_DAY_MIN, le=MEALS_PER_DAY_MAX)]
    diet_type: DietType = DietType.OMNIVORE
    dietary_restrictions: Annotated[str, Field(max_length=500)] | None = Field(
        None, description="A free-text note; it does not filter (algorithms.md 5.2)"
    )


class AcceptPlanRequest(BaseModel):
    start_date: date | None = Field(None, description="Defaults to today; end = start + 56 days")


class MealFoodItemOut(BaseModel):
    food_item_id: int
    name: str
    grams: float


class MealOut(BaseModel):
    id: int
    day_index: int
    meal_type: MealType
    meal_order: int
    planned_time: time
    planned_cals: int
    planned_protein: float
    planned_fat: float
    planned_carbs: float
    items: list[MealFoodItemOut]


class DietPlanOut(BaseModel):
    id: int
    name: str
    goal: Goal
    diet_type: DietType
    meals_per_day: int
    generated_at: datetime
    start_date: date | None
    end_date: date | None
    daily_cal_goal: int
    protein_goal: float
    fat_goal: float
    carbs_goal: float
    status: Literal["draft", "active", "archived"]
    dietary_restrictions: str | None
    meals: list[MealOut]

    @classmethod
    def of(cls, p: DietPlanView) -> "DietPlanOut":
        return cls(
            id=p.id,
            name=p.name,
            goal=p.goal,
            diet_type=p.diet_type,
            meals_per_day=p.meals_per_day,
            generated_at=p.generated_at,
            start_date=p.start_date,
            end_date=p.end_date,
            daily_cal_goal=p.daily_cal_goal,
            protein_goal=float(p.protein_goal),
            fat_goal=float(p.fat_goal),
            carbs_goal=float(p.carbs_goal),
            status=p.status,
            dietary_restrictions=p.dietary_restrictions,
            meals=[
                MealOut(
                    id=m.id,
                    day_index=m.day_index,
                    meal_type=m.meal_type,
                    meal_order=m.meal_order,
                    planned_time=m.planned_time,
                    planned_cals=m.planned_cals,
                    planned_protein=float(m.planned_protein),
                    planned_fat=float(m.planned_fat),
                    planned_carbs=float(m.planned_carbs),
                    items=[
                        MealFoodItemOut(
                            food_item_id=i.food_item_id, name=i.name, grams=float(i.grams)
                        )
                        for i in m.items
                    ],
                )
                for m in p.meals
            ],
        )


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[DietPlanService, Depends(get_diet_plan_service)]
UNAUTHORIZED = _error("Missing, expired or invalid token")
NOT_FOUND = _error("No such plan of the user")


@router.post(
    "/generate",
    operation_id="generateDietPlan",
    summary="Generate a draft 7-day diet plan (FR-P6)",
    status_code=201,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: _error("No profile yet")},
)
async def generate(body: GenerateDietPlanRequest, user: User, service: Service) -> DietPlanOut:
    request = DietRequest(body.meals_per_day, body.diet_type, body.dietary_restrictions)
    return DietPlanOut.of(await service.generate(user.id, request))


@router.get(
    "/active",
    operation_id="getActiveDietPlan",
    summary="The active diet plan",
    responses={401: UNAUTHORIZED, 404: _error("No active plan")},
)
async def get_active(user: User, service: Service) -> DietPlanOut:
    return DietPlanOut.of(await service.get_active(user.id))


@router.get(
    "/{plan_id:int}",
    operation_id="getDietPlan",
    summary="A diet plan of the user (draft, active or archived)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def get_plan(plan_id: PlanId, user: User, service: Service) -> DietPlanOut:
    return DietPlanOut.of(await service.get(user.id, plan_id))


@router.post(
    "/{plan_id:int}/accept",
    operation_id="acceptDietPlan",
    summary="Accept a draft; archives the previous active plan (FR-P7)",
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        404: NOT_FOUND,
        409: _error("The plan is not a draft"),
    },
)
async def accept(
    plan_id: PlanId,
    user: User,
    service: Service,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    body: Annotated[AcceptPlanRequest | None, Body()] = None,
) -> DietPlanOut:
    account = await users.get_by_id(user.id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    start = body.start_date if body else None
    return DietPlanOut.of(
        await service.accept(user.id, plan_id, start, account.timezone, datetime.now(UTC))
    )
