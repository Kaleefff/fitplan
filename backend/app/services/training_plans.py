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
from app.domain.constants import (
    PLAN_DURATION_DAYS,
    SWAP_ABOVE_LEVEL,
    SWAP_ALREADY_IN_SESSION,
    SWAP_EXCLUDED_BY_INJURY,
    SWAP_NEEDS_EQUIPMENT,
    SWAP_OTHER_MUSCLE_GROUP,
    SWAP_SAME_EXERCISE,
    SWAP_UNKNOWN_EXERCISE,
    DifficultyLevel,
    Equipment,
    Goal,
)
from app.domain.schedule import ScheduledSession, next_session
from app.domain.training import (
    ActiveInjury,
    ExerciseInfo,
    GeneratedPlan,
    InsufficientExercisesError,
    generate_training_plan,
    swap_problems,
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
    original_exercise_id: int | None  # the planned exercise before a swap (4.9)


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


@dataclass(frozen=True)
class SwapContext:
    """What 4.9 checks a swap of a session exercise against."""

    exercise_id: int  # the exercise now in the slot
    original_exercise_id: int | None  # the planned one, when the slot was swapped
    plan_status: str
    experience_level: DifficultyLevel  # the plan's snapshot
    equipment: Equipment  # the plan's snapshot
    session_exercise_ids: frozenset[int]  # every exercise in the session, current included


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

    async def lock_session(self, user_id: int, session_id: int) -> tuple[int, str] | None:
        """(plan id, plan status) of the user's session, locked; None if not theirs."""
        ...

    async def weekday_taken(self, plan_id: int, session_id: int, day_of_week: int) -> bool: ...

    async def set_weekday(self, session_id: int, day_of_week: int) -> None: ...

    async def workout_days(self, session_ids: list[int], since: date) -> set[tuple[int, date]]:
        """(session id, log date) of the live workouts of these sessions from `since`."""
        ...

    async def swap_context(
        self, user_id: int, session_exercise_id: int, *, lock: bool = False
    ) -> SwapContext | None:
        """The plan snapshot and session of the user's session exercise; None if not theirs.
        `lock` takes the plan's row lock, as for every change of a plan."""
        ...

    async def set_session_exercise(self, session_exercise_id: int, values: dict) -> None:
        """Writes the given `session_exercise` columns."""
        ...

    async def session_exercise(self, session_exercise_id: int) -> SessionExerciseView: ...

    async def profile_limits(self, user_id: int) -> tuple[DifficultyLevel, Equipment] | None:
        """The profile's experience level and equipment; None without a profile."""
        ...


TrainingPlanUnitOfWork = Callable[[], AbstractAsyncContextManager[TrainingPlanStore]]


SWAP_MESSAGES = {
    SWAP_UNKNOWN_EXERCISE: "No such exercise",
    SWAP_SAME_EXERCISE: "The exercise is already in this slot",
    SWAP_OTHER_MUSCLE_GROUP: "The exercise trains another main muscle group",
    SWAP_ALREADY_IN_SESSION: "The exercise is already in this session",
    SWAP_ABOVE_LEVEL: "The exercise is above the plan's level",
    SWAP_NEEDS_EQUIPMENT: "The exercise needs more equipment than the plan has",
    SWAP_EXCLUDED_BY_INJURY: "The exercise is excluded by an active injury",
}


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

    async def update_session_exercise(
        self, user_id: int, session_exercise_id: int, changes: dict
    ) -> SessionExerciseView:
        """api-rules.md "Plans": sets, reps, rest and weight of a draft or active plan; an
        archived plan is 409."""
        async with self._unit_of_work() as store:
            await self._editable(store, user_id, session_exercise_id)
            await store.set_session_exercise(session_exercise_id, changes)
            return await store.session_exercise(session_exercise_id)

    async def swap(
        self, user_id: int, session_exercise_id: int, exercise_id: int
    ) -> SessionExerciseView:
        """4.9: keeps sets, reps, rest and weight; stores the planned exercise in
        `original_exercise_id`, and swapping back to it clears it."""
        async with self._unit_of_work() as store:
            context = await self._editable(store, user_id, session_exercise_id)
            catalogue = {e.id: e for e in await store.catalogue()}
            problems = swap_problems(
                catalogue[context.exercise_id],
                catalogue.get(exercise_id),
                context.session_exercise_ids,
                context.experience_level,
                context.equipment,
                await store.active_injuries(user_id),
            )
            if problems:
                raise AppError(
                    422,
                    ErrorCode.INVALID_SWAP,
                    "The exercise cannot replace this one",
                    [
                        {"field": "body.exercise_id", "code": code, "message": SWAP_MESSAGES[code]}
                        for code in problems
                    ],
                )
            original = context.original_exercise_id or context.exercise_id
            await store.set_session_exercise(
                session_exercise_id,
                {
                    "exercise_id": exercise_id,
                    "original_exercise_id": None if exercise_id == original else original,
                },
            )
            return await store.session_exercise(session_exercise_id)

    @staticmethod
    async def _editable(
        store: TrainingPlanStore, user_id: int, session_exercise_id: int
    ) -> SwapContext:
        context = await store.swap_context(user_id, session_exercise_id, lock=True)
        if context is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
        if context.plan_status == "archived":
            raise AppError(409, ErrorCode.CONFLICT, "The plan is archived")
        return context

    async def move_session(self, user_id: int, session_id: int, day_of_week: int) -> SessionView:
        """api-rules.md "Plans": a weekday already used in the plan is 409; an archived plan
        cannot change (409, as for its exercises; questions.md, B-14)."""
        async with self._unit_of_work() as store:
            found = await store.lock_session(user_id, session_id)
            if found is None:
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
            plan_id, status = found
            if status == "archived":
                raise AppError(409, ErrorCode.CONFLICT, "The plan is archived")
            if await store.weekday_taken(plan_id, session_id, day_of_week):
                raise AppError(
                    409,
                    ErrorCode.CONFLICT,
                    "Another session of the plan is on that weekday",
                    [
                        {
                            "field": "body.day_of_week",
                            "code": "conflict",
                            "message": "Another session of the plan is on that weekday",
                        }
                    ],
                )
            await store.set_weekday(session_id, day_of_week)
            plan = await store.get_plan(user_id, plan_id)
        return next(s for s in plan.sessions if s.id == session_id)
