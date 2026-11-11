"""Nutrition logs and the daily summary (B-21; FR-A3, FR-R2; api-rules.md "Logs")."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, Field, model_validator

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_nutrition_log_service,
    get_user_repository,
)
from app.api.v1.diet_plans import MealFoodItemOut
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.db.repositories.nutrition_logs import ItemIn, Macros, NutritionLogIn, NutritionLogView
from app.domain.constants import MealType
from app.domain.rounding import round_half_up
from app.services.auth import UserRepository
from app.services.nutrition_logs import NutritionLogService, today

router = APIRouter(tags=["nutrition"])

INT_MAX = 2_147_483_647
Id = Annotated[int, Field(ge=1, le=INT_MAX)]
Hunger = Annotated[int, Field(ge=1, le=10)]


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[NutritionLogService, Depends(get_nutrition_log_service)]
Users = Annotated[UserRepository, Depends(get_user_repository)]
LogId = Annotated[int, Path(ge=1, le=INT_MAX)]
UNAUTHORIZED = _error("Missing, expired or invalid token")
NOT_FOUND = _error("No such live log of the user")


class ItemBody(BaseModel):
    food_item_id: Id
    grams: Annotated[float, Field(gt=0, le=99999.9)]

    def to_input(self) -> ItemIn:
        return ItemIn(self.food_item_id, Decimal(str(self.grams)))


class NutritionLogBody(BaseModel):
    client_uuid: uuid.UUID | None = None
    log_date: date
    meal_type: MealType
    planned_meal_id: Id | None = None
    hunger_level_before: Hunger | None = None
    hunger_level_after: Hunger | None = None
    items: Annotated[list[ItemBody], Field(min_length=1)]

    def to_input(self) -> NutritionLogIn:
        return NutritionLogIn(
            client_uuid=self.client_uuid,
            log_date=self.log_date,
            meal_type=self.meal_type,
            planned_meal_id=self.planned_meal_id,
            hunger_level_before=self.hunger_level_before,
            hunger_level_after=self.hunger_level_after,
            items=tuple(i.to_input() for i in self.items),
        )


class NutritionLogPatchBody(BaseModel):
    """At least one field. `log_date`, `meal_type` and `items` may not be null; the
    planned meal and hunger levels may be cleared with null."""

    log_date: date = Field(default=None)
    meal_type: MealType = Field(default=None)
    planned_meal_id: Id | None = None
    hunger_level_before: Hunger | None = None
    hunger_level_after: Hunger | None = None
    items: Annotated[list[ItemBody], Field(min_length=1)] = Field(
        default=None, description="Replaces all items"
    )

    @model_validator(mode="after")
    def _some_field(self) -> "NutritionLogPatchBody":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class NutritionLogOut(BaseModel):
    id: int
    client_uuid: uuid.UUID
    log_date: date
    meal_type: MealType
    planned_meal_id: int | None
    meal_photo_url: str | None
    ai_confidence: float | None
    ai_was_edited: bool | None
    actual_cals: float
    actual_protein: float
    actual_fat: float
    actual_carbs: float
    hunger_level_before: int | None
    hunger_level_after: int | None
    logged_at: datetime
    items: list[MealFoodItemOut]

    @classmethod
    def of(cls, log: NutritionLogView) -> "NutritionLogOut":
        return cls(
            id=log.id,
            client_uuid=log.client_uuid,
            log_date=log.log_date,
            meal_type=log.meal_type,
            planned_meal_id=log.planned_meal_id,
            meal_photo_url=log.meal_photo_url,
            ai_confidence=None if log.ai_confidence is None else float(log.ai_confidence),
            ai_was_edited=log.ai_was_edited,
            actual_cals=float(log.actual_cals),
            actual_protein=float(log.actual_protein),
            actual_fat=float(log.actual_fat),
            actual_carbs=float(log.actual_carbs),
            hunger_level_before=log.hunger_level_before,
            hunger_level_after=log.hunger_level_after,
            logged_at=log.logged_at,
            items=[
                MealFoodItemOut(food_item_id=i.food_item_id, name=i.name, grams=float(i.grams))
                for i in log.items
            ],
        )


class NutritionLogPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[NutritionLogOut]


class MacrosOut(BaseModel):
    kcal: float
    protein: float
    fat: float
    carbs: float

    @classmethod
    def of(cls, m: Macros | None) -> "MacrosOut | None":
        if m is None:
            return None
        return cls(
            kcal=float(m.kcal), protein=float(m.protein), fat=float(m.fat), carbs=float(m.carbs)
        )


class DailySummaryOut(BaseModel):
    date: date
    targets: MacrosOut | None
    totals: MacrosOut
    remaining: MacrosOut | None
    avg_hunger_before: float | None
    avg_hunger_after: float | None
    logs: list[NutritionLogOut]


def _one_decimal(value: Decimal | None) -> float | None:
    return None if value is None else float(round_half_up(value, 1))


async def _timezone(users: UserRepository, user: CurrentUser) -> str:
    account = await users.get_by_id(user.id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    return account.timezone


@router.get(
    "/nutrition-logs",
    operation_id="listNutritionLogs",
    summary="Nutrition log history",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def list_nutrition_logs(
    user: User,
    service: Service,
    date_from: Annotated[
        date | None, Query(alias="from", description="First day, inclusive")
    ] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Last day, inclusive")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> NutritionLogPage:
    total, logs = await service.list_logs(user.id, date_from, date_to, limit, offset)
    return NutritionLogPage(
        total=total, limit=limit, offset=offset, items=[NutritionLogOut.of(log) for log in logs]
    )


@router.post(
    "/nutrition-logs",
    operation_id="createNutritionLog",
    summary="Log a meal manually, with hunger levels (FR-A3)",
    status_code=201,
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        409: _error("client_uuid of the user's deleted log"),
    },
)
async def create_nutrition_log(
    body: NutritionLogBody, user: User, service: Service, users: Users
) -> NutritionLogOut:
    timezone = await _timezone(users, user)
    log = await service.create(user.id, body.to_input(), timezone, datetime.now(UTC))
    return NutritionLogOut.of(log)


@router.patch(
    "/nutrition-logs/{nutrition_log_id}",
    operation_id="updateNutritionLog",
    summary="Correct a nutrition log (FR-A3)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def update_nutrition_log(
    nutrition_log_id: LogId, body: NutritionLogPatchBody, user: User, service: Service, users: Users
) -> NutritionLogOut:
    timezone = await _timezone(users, user)
    changes = {f: getattr(body, f) for f in body.model_fields_set if f != "items"}
    items = None if body.items is None else [i.to_input() for i in body.items]
    log = await service.update(
        user.id, nutrition_log_id, changes, items, timezone, datetime.now(UTC)
    )
    return NutritionLogOut.of(log)


@router.delete(
    "/nutrition-logs/{nutrition_log_id}",
    operation_id="deleteNutritionLog",
    summary="Delete a nutrition log (soft)",
    status_code=204,
    response_class=Response,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def delete_nutrition_log(nutrition_log_id: LogId, user: User, service: Service) -> Response:
    await service.delete(user.id, nutrition_log_id)
    return Response(status_code=204)


@router.get(
    "/nutrition/daily-summary",
    operation_id="getDailySummary",
    summary="Totals of a day against the active diet plan targets",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def get_daily_summary(
    user: User,
    service: Service,
    users: Users,
    day: Annotated[
        date | None,
        Query(alias="date", description="Defaults to today in the user's time zone"),
    ] = None,
) -> DailySummaryOut:
    if day is None:
        day = today(await _timezone(users, user), datetime.now(UTC))
    summary = await service.daily_summary(user.id, day)
    return DailySummaryOut(
        date=summary.date,
        targets=MacrosOut.of(summary.targets),
        totals=MacrosOut.of(summary.totals),
        remaining=MacrosOut.of(summary.remaining),
        avg_hunger_before=_one_decimal(summary.avg_hunger_before),
        avg_hunger_after=_one_decimal(summary.avg_hunger_after),
        logs=[NutritionLogOut.of(log) for log in summary.logs],
    )
