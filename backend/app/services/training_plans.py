"""Training plans: generate a draft, read, accept (B-11; FR-P1, FR-P2, FR-P3, FR-P7).

The plan itself comes from `app/domain/training.py` (algorithms.md section 4); this
module loads its inputs and stores its result. Generation and acceptance take the
user's row lock, so two requests of one user never interleave.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.core.errors import AppError, ErrorCode
from app.domain.constants import PLAN_DURATION_DAYS, DifficultyLevel, Equipment, Goal
from app.domain.schedule import ScheduledSession, next_session
from app.domain.training import (
    ActiveInjury,
    ExerciseInfo,
    GeneratedPlan,
    InsufficientExercisesError,
    generate_training_plan,
)


@dataclass(frozen=True)
class PlanRequest:
    goal: Goal
    num_training_days: int
    experience_level: DifficultyLevel
    equipment: Equipment


@dataclass(frozen=True)
class SessionExerciseView:
    id: int
    exercise_id: int
    exercise_name: str
    sort_order: int
    planned_sets: int
    planned_reps: int
    planned_weight: Decimal | None
    rest_seconds: int


@dataclass(frozen=True)
class SessionView:
    id: int
    session_order: int
    session_name: str
    day_of_week: int
    estimated_duration: int
    exercises: tuple[SessionExerciseView, ...]


@dataclass(frozen=True)
class PlanView:
    id: int
    plan_name: str
    goal: str
    num_training_days: int
    experience_level: str
    equipment: str
    generated_at: datetime
    start_date: date | None
    end_date: date | None
    status: str
    skipped_muscle_groups: tuple[str, ...]
    sessions: tuple[SessionView, ...]


class TrainingPlanStore(Protocol):
    """Every call of one unit of work runs in the same transaction."""

    async def lock_user(self, user_id: int) -> None: ...

    async def catalogue(self) -> list[ExerciseInfo]: ...

    async def active_injuries(self, user_id: int) -> list[ActiveInjury]: ...

    async def replace_draft(
        self, user_id: int, request: PlanRequest, plan: GeneratedPlan
    ) -> int: ...

    async def get_plan(self, user_id: int, plan_id: int) -> PlanView | None: ...

    async def get_active(self, user_id: int) -> PlanView | None: ...

    async def activate(self, user_id: int, plan_id: int, start: date, end: date) -> None: ...

    async def workout_days(self, session_ids: list[int], since: date) -> set[tuple[int, date]]:
        """(session id, log date) of the live workouts of these sessions from `since`."""
        ...


TrainingPlanUnitOfWork = Callable[[], AbstractAsyncContextManager[TrainingPlanStore]]


class TrainingPlanService:
    def __init__(self, unit_of_work: TrainingPlanUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def generate(self, user_id: int, request: PlanRequest) -> PlanView:
        """4.8: a new draft replaces the previous one; on 422 nothing is stored."""
        async with self._unit_of_work() as store:
            await store.lock_user(user_id)
            try:
                plan = generate_training_plan(
                    request.goal,
                    request.num_training_days,
                    request.experience_level,
                    request.equipment,
                    await store.active_injuries(user_id),
                    await store.catalogue(),
                )
            except InsufficientExercisesError as error:
                raise AppError(
                    422,
                    ErrorCode.INSUFFICIENT_EXERCISES,
                    "Not enough eligible exercises for this plan",
                    error.details,
                ) from None
            plan_id = await store.replace_draft(user_id, request, plan)
            return await store.get_plan(user_id, plan_id)

    async def get(self, user_id: int, plan_id: int) -> PlanView:
        async with self._unit_of_work() as store:
            plan = await store.get_plan(user_id, plan_id)
        if plan is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
        return plan

    async def get_active(self, user_id: int) -> PlanView:
        async with self._unit_of_work() as store:
            plan = await store.get_active(user_id)
        if plan is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "No active training plan")
        return plan

    async def accept(
        self, user_id: int, plan_id: int, start: date | None, timezone: str, now: datetime
    ) -> PlanView:
        """4.8: only a draft; archives the active plan; end = start + 56 days."""
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

    async def next_session(
        self, user_id: int, timezone: str, now: datetime
    ) -> tuple[PlanView, SessionView, date]:
        """api-rules.md "Plans": GET /sessions/next; 404 without an active plan or a date."""
        today = now.astimezone(ZoneInfo(timezone)).date()
        async with self._unit_of_work() as store:
            plan = await store.get_active(user_id)
            if plan is not None:
                done = await store.workout_days([s.id for s in plan.sessions], today)
        if plan is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "No active training plan")
        found = next_session(
            [ScheduledSession(s.id, s.session_order, s.day_of_week) for s in plan.sessions],
            plan.start_date,
            plan.end_date,
            today,
            done,
        )
        if found is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "No session left in the active plan")
        scheduled, day = found
        return plan, next(s for s in plan.sessions if s.id == scheduled.id), day
