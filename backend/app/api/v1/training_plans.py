from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field, model_validator

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_training_plan_service,
    get_user_repository,
)
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.domain.constants import (
    TRAINING_DAYS_MAX,
    TRAINING_DAYS_MIN,
    DifficultyLevel,
    Equipment,
    Goal,
)
from app.domain.rounding import round_half_up
from app.services.auth import UserRepository
from app.services.training_plans import (
    PlanRequest,
    PlanView,
    SessionExerciseView,
    SessionView,
    TrainingPlanService,
)

router = APIRouter(prefix="/training-plans", tags=["training"])

INT_MAX = 2_147_483_647
PlanId = Annotated[int, Path(ge=1, le=INT_MAX)]


class GenerateTrainingPlanRequest(BaseModel):
    goal: Goal
    num_training_days: Annotated[int, Field(ge=TRAINING_DAYS_MIN, le=TRAINING_DAYS_MAX)]
    experience_level: DifficultyLevel
    equipment: Equipment


class AcceptPlanRequest(BaseModel):
    start_date: date | None = Field(None, description="Defaults to today; end = start + 56 days")


class SessionExerciseOut(BaseModel):
    id: int
    exercise_id: int
    exercise_name: str
    sort_order: int
    planned_sets: int
    planned_reps: int
    planned_weight: float | None = Field(description="kg; null until the baseline workout")
    rest_seconds: int
    original_exercise_id: int | None = Field(
        description="The planned exercise when this one was swapped in (algorithms.md 4.9)"
    )

    @classmethod
    def of(cls, e: SessionExerciseView) -> "SessionExerciseOut":
        return cls(
            id=e.id,
            exercise_id=e.exercise_id,
            exercise_name=e.exercise_name,
            sort_order=e.sort_order,
            planned_sets=e.planned_sets,
            planned_reps=e.planned_reps,
            planned_weight=None if e.planned_weight is None else float(e.planned_weight),
            rest_seconds=e.rest_seconds,
            original_exercise_id=e.original_exercise_id,
        )


class TrainingSessionOut(BaseModel):
    id: int
    session_order: int
    session_name: str
    day_of_week: int = Field(description="1 = Monday")
    estimated_duration: int = Field(description="minutes")
    exercises: list[SessionExerciseOut]


class TrainingPlanOut(BaseModel):
    id: int
    plan_name: str
    goal: Goal
    num_training_days: int
    experience_level: DifficultyLevel
    equipment: Equipment
    generated_at: datetime
    start_date: date | None
    end_date: date | None
    status: Literal["draft", "active", "archived"]
    skipped_muscle_groups: list[str]
    sessions: list[TrainingSessionOut]

    @classmethod
    def of(cls, plan: PlanView) -> "TrainingPlanOut":
        return cls(
            id=plan.id,
            plan_name=plan.plan_name,
            goal=plan.goal,
            num_training_days=plan.num_training_days,
            experience_level=plan.experience_level,
            equipment=plan.equipment,
            generated_at=plan.generated_at,
            start_date=plan.start_date,
            end_date=plan.end_date,
            status=plan.status,
            skipped_muscle_groups=list(plan.skipped_muscle_groups),
            sessions=[session_out(s) for s in plan.sessions],
        )


def session_out(s: SessionView) -> TrainingSessionOut:
    return TrainingSessionOut(
        id=s.id,
        session_order=s.session_order,
        session_name=s.session_name,
        day_of_week=s.day_of_week,
        estimated_duration=s.estimated_duration,
        exercises=[SessionExerciseOut.of(e) for e in s.exercises],
    )


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[TrainingPlanService, Depends(get_training_plan_service)]
UNAUTHORIZED = _error("Missing, expired or invalid token")
NOT_FOUND = _error("No such plan of the user")


@router.post(
    "/generate",
    operation_id="generateTrainingPlan",
    summary="Generate a draft training plan (FR-P1, FR-P2, FR-P3)",
    status_code=201,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def generate(
    body: GenerateTrainingPlanRequest, user: User, service: Service
) -> TrainingPlanOut:
    request = PlanRequest(body.goal, body.num_training_days, body.experience_level, body.equipment)
    return TrainingPlanOut.of(await service.generate(user.id, request))


@router.get(
    "/active",
    operation_id="getActiveTrainingPlan",
    summary="The active training plan",
    responses={401: UNAUTHORIZED, 404: _error("No active plan")},
)
async def get_active(user: User, service: Service) -> TrainingPlanOut:
    return TrainingPlanOut.of(await service.get_active(user.id))


@router.get(
    "/{plan_id:int}",
    operation_id="getTrainingPlan",
    summary="A training plan of the user (draft, active or archived)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def get_plan(plan_id: PlanId, user: User, service: Service) -> TrainingPlanOut:
    return TrainingPlanOut.of(await service.get(user.id, plan_id))


@router.post(
    "/{plan_id:int}/accept",
    operation_id="acceptTrainingPlan",
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
) -> TrainingPlanOut:
    account = await users.get_by_id(user.id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    start = body.start_date if body else None
    plan = await service.accept(user.id, plan_id, start, account.timezone, datetime.now(UTC))
    return TrainingPlanOut.of(plan)


sessions_router = APIRouter(tags=["workouts"])
exercises_router = APIRouter(tags=["training"])


class NextSessionOut(BaseModel):
    training_plan_id: int
    date: date
    session: TrainingSessionOut


@sessions_router.get(
    "/sessions/next",
    operation_id="getNextSession",
    summary="Next training session of the active plan",
    responses={401: UNAUTHORIZED, 404: _error("No active plan or no session left")},
)
async def get_next_session(
    user: User,
    service: Service,
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> NextSessionOut:
    account = await users.get_by_id(user.id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    plan, session, day = await service.next_session(user.id, account.timezone, datetime.now(UTC))
    return NextSessionOut(training_plan_id=plan.id, date=day, session=session_out(session))


# ---------------------------------------------------------------- plan edits (B-13, FR-A1)

SMALLINT_MAX = 32_767  # session_exercise columns are SMALLINT
SessionExerciseId = Annotated[int, Path(ge=1, le=INT_MAX)]


class SessionExercisePatchBody(BaseModel):
    """At least one field; a field that is sent may not be null."""

    planned_sets: int = Field(default=None, ge=1, le=SMALLINT_MAX)
    planned_reps: int = Field(default=None, ge=1, le=SMALLINT_MAX)
    planned_weight: float = Field(default=None, ge=0, le=999.99, description="kg")
    rest_seconds: int = Field(default=None, ge=0, le=SMALLINT_MAX)

    @model_validator(mode="after")
    def _some_field(self) -> "SessionExercisePatchBody":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class SwapBody(BaseModel):
    exercise_id: int = Field(ge=1, le=INT_MAX)


EDIT_RESPONSES = {
    **VALIDATION_ERROR_RESPONSE,
    401: UNAUTHORIZED,
    404: _error("No such session exercise of the user"),
    409: _error("The plan is archived"),
}


@exercises_router.patch(
    "/session-exercises/{session_exercise_id}",
    operation_id="updateSessionExercise",
    summary="Edit sets, reps, rest or weight of a planned exercise (FR-A1)",
    responses=EDIT_RESPONSES,
)
async def update_session_exercise(
    session_exercise_id: SessionExerciseId,
    body: SessionExercisePatchBody,
    user: User,
    service: Service,
) -> SessionExerciseOut:
    changes = {f: getattr(body, f) for f in body.model_fields_set}
    if "planned_weight" in changes:
        changes["planned_weight"] = round_half_up(Decimal(str(changes["planned_weight"])), 2)
    return SessionExerciseOut.of(
        await service.update_session_exercise(user.id, session_exercise_id, changes)
    )


@exercises_router.put(
    "/session-exercises/{session_exercise_id}/swap",
    operation_id="swapSessionExercise",
    summary="Swap an exercise for an alternative (FR-A1)",
    responses=EDIT_RESPONSES,
)
async def swap_session_exercise(
    session_exercise_id: SessionExerciseId, body: SwapBody, user: User, service: Service
) -> SessionExerciseOut:
    return SessionExerciseOut.of(await service.swap(user.id, session_exercise_id, body.exercise_id))
