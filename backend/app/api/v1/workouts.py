import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_current_user, get_user_repository, get_workout_service
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.services.auth import UserRepository
from app.services.workouts import (
    ExerciseIn,
    SetIn,
    WorkoutIn,
    WorkoutResult,
    WorkoutService,
    WorkoutView,
)

router = APIRouter(tags=["workouts"], responses=VALIDATION_ERROR_RESPONSE)

# column ranges (api-rules.md: out-of-range input is 422, never 500)
SMALLINT_MAX = 32767
INT_MAX = 2_147_483_647
WEIGHT_MAX = 999.99  # NUMERIC(5, 2)

Id = Annotated[int, Field(ge=1, le=INT_MAX)]
SmallCount = Annotated[int, Field(ge=1, le=SMALLINT_MAX)]
Rpe = Annotated[int, Field(ge=1, le=10)]


class WorkoutSetBody(BaseModel):
    set_number: SmallCount
    reps: Annotated[int, Field(ge=0, le=SMALLINT_MAX)]
    weight: Annotated[float, Field(ge=0, le=WEIGHT_MAX, description="kg, 0 for bodyweight")]
    completed: bool
    rpe: Rpe | None = None


class WorkoutExerciseBody(BaseModel):
    exercise_id: Id
    session_exercise_id: Id | None = None
    sort_order: SmallCount
    sets: Annotated[list[WorkoutSetBody], Field(min_length=1)]


class WorkoutBody(BaseModel):
    client_uuid: uuid.UUID | None = None
    training_session_id: Id | None = None
    log_date: date
    rpe_rating: Rpe
    exercises: Annotated[list[WorkoutExerciseBody], Field(min_length=1)]

    def to_input(self) -> WorkoutIn:
        return WorkoutIn(
            client_uuid=self.client_uuid,
            training_session_id=self.training_session_id,
            log_date=self.log_date,
            rpe_rating=self.rpe_rating,
            exercises=tuple(
                ExerciseIn(
                    exercise_id=e.exercise_id,
                    session_exercise_id=e.session_exercise_id,
                    sort_order=e.sort_order,
                    sets=tuple(
                        SetIn(s.set_number, s.reps, Decimal(str(s.weight)), s.completed, s.rpe)
                        for s in e.sets
                    ),
                )
                for e in self.exercises
            ),
        )


class WorkoutSetOut(BaseModel):
    set_number: int
    reps: int
    weight: float
    completed: bool
    rpe: int | None


class WorkoutExerciseOut(BaseModel):
    exercise_id: int
    exercise_name: str
    session_exercise_id: int | None
    sort_order: int
    sets: list[WorkoutSetOut]


class WorkoutOut(BaseModel):
    id: int
    training_session_id: int | None
    log_date: date
    rpe_rating: int
    logged_at: datetime
    exercises: list[WorkoutExerciseOut]

    @classmethod
    def of(cls, view: WorkoutView) -> "WorkoutOut":
        return cls(
            id=view.id,
            training_session_id=view.training_session_id,
            log_date=view.log_date,
            rpe_rating=view.rpe_rating,
            logged_at=view.logged_at,
            exercises=[
                WorkoutExerciseOut(
                    exercise_id=e.exercise_id,
                    exercise_name=e.exercise_name,
                    session_exercise_id=e.session_exercise_id,
                    sort_order=e.sort_order,
                    sets=[
                        WorkoutSetOut(
                            set_number=s.set_number,
                            reps=s.reps,
                            weight=float(s.weight),
                            completed=s.completed,
                            rpe=s.rpe,
                        )
                        for s in e.sets
                    ],
                )
                for e in view.exercises
            ],
        )


class PlanAdjustmentOut(BaseModel):
    session_exercise_id: int
    reason: Literal["baseline", "progression", "reduce_high_rpe", "reduce_incomplete_set"]
    old_sets: int
    new_sets: int
    old_reps: int
    new_reps: int
    old_weight: float | None
    new_weight: float | None


class PersonalRecordOut(BaseModel):
    id: int
    exercise_id: int
    max_weight: float
    max_reps: int
    achieved_date: date


class WorkoutResultOut(BaseModel):
    workout: WorkoutOut
    adjustments: list[PlanAdjustmentOut]
    new_personal_records: list[PersonalRecordOut]

    @classmethod
    def of(cls, result: WorkoutResult) -> "WorkoutResultOut":
        def kg(value: Decimal | None) -> float | None:
            return None if value is None else float(value)

        return cls(
            workout=WorkoutOut.of(result.workout),
            adjustments=[
                PlanAdjustmentOut(
                    session_exercise_id=a.session_exercise_id,
                    reason=a.reason,
                    old_sets=a.old_sets,
                    new_sets=a.new_sets,
                    old_reps=a.old_reps,
                    new_reps=a.new_reps,
                    old_weight=kg(a.old_weight),
                    new_weight=kg(a.new_weight),
                )
                for a in result.adjustments
            ],
            new_personal_records=[
                PersonalRecordOut(
                    id=r.id,
                    exercise_id=r.exercise_id,
                    max_weight=float(r.max_weight),
                    max_reps=r.max_reps,
                    achieved_date=r.achieved_date,
                )
                for r in result.new_personal_records
            ],
        )


class WorkoutPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WorkoutOut]


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[WorkoutService, Depends(get_workout_service)]


@router.post(
    "/workouts",
    operation_id="createWorkout",
    summary="Log a workout with per-set data and RPE (FR-A2)",
    status_code=201,
    responses={
        401: _error("Missing, expired or invalid token"),
        409: _error("client_uuid already used by a deleted workout or another user"),
    },
)
async def create_workout(
    body: WorkoutBody,
    user: User,
    service: Service,
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> WorkoutResultOut:
    account = await users.get_by_id(user.id)
    if account is None:  # deleted while the access token is still valid
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    result = await service.create(user.id, account.timezone, body.to_input(), datetime.now(UTC))
    return WorkoutResultOut.of(result)


@router.get(
    "/workouts",
    operation_id="listWorkouts",
    summary="Workout history",
    responses={401: _error("Missing, expired or invalid token")},
)
async def list_workouts(
    user: User,
    service: Service,
    date_from: Annotated[
        date | None, Query(alias="from", description="First day, inclusive")
    ] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Last day, inclusive")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> WorkoutPage:
    total, items = await service.list(user.id, date_from, date_to, limit, offset)
    return WorkoutPage(
        total=total, limit=limit, offset=offset, items=[WorkoutOut.of(w) for w in items]
    )


@router.put(
    "/workouts/{workout_id}",
    operation_id="updateWorkout",
    summary="Correct a logged workout (FR-A2)",
    responses={
        401: _error("Missing, expired or invalid token"),
        404: _error("No such workout of the user"),
    },
)
async def update_workout(
    workout_id: Annotated[int, Path(ge=1, le=INT_MAX)],
    body: WorkoutBody,
    user: User,
    service: Service,
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> WorkoutOut:
    account = await users.get_by_id(user.id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    view = await service.update(
        user.id, account.timezone, workout_id, body.to_input(), datetime.now(UTC)
    )
    return WorkoutOut.of(view)


@router.delete(
    "/workouts/{workout_id}",
    operation_id="deleteWorkout",
    summary="Delete a workout (soft)",
    status_code=204,
    response_class=Response,
    responses={
        401: _error("Missing, expired or invalid token"),
        404: _error("No such workout of the user"),
    },
)
async def delete_workout(
    workout_id: Annotated[int, Path(ge=1, le=INT_MAX)], user: User, service: Service
) -> Response:
    await service.delete(user.id, workout_id)
    return Response(status_code=204)
