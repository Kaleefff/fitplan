from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_analytics_service, get_current_user, get_user_repository
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.domain.rounding import round_half_up
from app.services.analytics import AnalyticsService
from app.services.auth import UserRepository

router = APIRouter(prefix="/analytics", tags=["analytics"])

Period = Literal["week", "month", "3months"]
Metric = Literal["weight", "tonnage", "workouts_per_week", "calories"]
PERIOD = Query(
    description="week = last 7 days, month = last 30 days, 3months = last 90 days (algorithms.md 8)"
)


def _round(value: float | Decimal | None, places: int) -> float | None:
    if value is None:
        return None
    return float(round_half_up(Decimal(str(value)), places))


class KeyLiftOut(BaseModel):
    exercise_id: int
    exercise_name: str
    first_e1rm: float
    best_e1rm: float


class AnalyticsSummaryOut(BaseModel):
    status: Literal["ok", "insufficient_data"]
    period: Period
    period_start: date
    period_end: date
    weight_change: float | None
    total_workouts: int | None
    avg_workouts_per_week: float | None
    avg_calories: float | None
    tonnage: float | None
    workout_compliance_pct: float | None
    diet_compliance_pct: float | None
    key_lifts: list[KeyLiftOut]


class ChartPointOut(BaseModel):
    date: date
    value: float


class ChartSeriesOut(BaseModel):
    status: Literal["ok", "insufficient_data"]
    metric: Metric
    period: Period
    points: list[ChartPointOut]


class GoalPredictionOut(BaseModel):
    status: Literal[
        "ok", "no_target", "insufficient_data", "goal_reached", "no_progress", "moving_away"
    ]
    estimated_date: date | None
    slope_kg_per_week: float | None
    r_squared: float | None
    warnings: list[Literal["low_fit", "gaps", "low_training_compliance"]]
    irregular_data: bool


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[AnalyticsService, Depends(get_analytics_service)]
Users = Annotated[UserRepository, Depends(get_user_repository)]
UNAUTHORIZED = _error("Missing, expired or invalid token")


async def _timezone(users: UserRepository, user_id: int) -> str:
    account = await users.get_by_id(user_id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    return account.timezone


@router.get(
    "/summary",
    operation_id="getAnalyticsSummary",
    summary="Metric tiles and compliance for a period (FR-R1, FR-R2, FR-R5)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def get_summary(
    user: User, service: Service, users: Users, period: Annotated[Period, PERIOD] = "week"
) -> AnalyticsSummaryOut:
    timezone = await _timezone(users, user.id)
    s = await service.summary(user.id, period, timezone, datetime.now(UTC))
    return AnalyticsSummaryOut(
        status=s.status,
        period=period,
        period_start=s.period_start,
        period_end=s.period_end,
        weight_change=_round(s.weight_change, 2),
        total_workouts=s.total_workouts,
        avg_workouts_per_week=_round(s.avg_workouts_per_week, 1),
        avg_calories=_round(s.avg_calories, 0),  # kcal are integers (algorithms.md 0)
        tonnage=_round(s.tonnage, 1),
        workout_compliance_pct=_round(s.workout_compliance_pct, 1),
        diet_compliance_pct=_round(s.diet_compliance_pct, 1),
        key_lifts=[
            KeyLiftOut(
                exercise_id=k.exercise_id,
                exercise_name=k.exercise_name,
                first_e1rm=_round(k.first_e1rm, 2),
                best_e1rm=_round(k.best_e1rm, 2),
            )
            for k in s.key_lifts
        ],
    )


@router.get(
    "/charts/{metric}",
    operation_id="getAnalyticsChart",
    summary="Chart series (FR-R3)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def get_chart(
    metric: Annotated[Metric, Path()],
    user: User,
    service: Service,
    users: Users,
    period: Annotated[Period, PERIOD] = "week",
) -> ChartSeriesOut:
    timezone = await _timezone(users, user.id)
    status, points = await service.chart(user.id, metric, period, timezone, datetime.now(UTC))
    return ChartSeriesOut(
        status=status,
        metric=metric,
        period=period,
        points=[ChartPointOut(date=day, value=_round(value, 2)) for day, value in points],
    )


@router.get(
    "/goal-prediction",
    operation_id="getGoalPrediction",
    summary="Predicted goal date from the weight trend (FR-R4)",
    responses={401: UNAUTHORIZED},
)
async def get_goal_prediction(user: User, service: Service, users: Users) -> GoalPredictionOut:
    timezone = await _timezone(users, user.id)
    p = await service.goal_prediction(user.id, timezone, datetime.now(UTC))
    return GoalPredictionOut(
        status=p.status.value,
        estimated_date=p.estimated_date,
        slope_kg_per_week=_round(p.slope_kg_per_week, 2),
        r_squared=_round(p.r_squared, 2),
        warnings=[w.value for w in p.warnings],
        irregular_data=p.irregular_data,
    )
