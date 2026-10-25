"""Workout logging with adaptation and personal records (B-15, B-16; FR-A2, FR-A4, FR-A5).

One workout is one transaction: the log, the plan changes with their `plan_adjustment`
rows, new personal records and their `achievement` notifications are stored together
(api-rules.md "Logs", algorithms.md section 6).
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.core.errors import AppError, ErrorCode
from app.domain.adaptation import Adjustment, LoggedSet, PlannedExercise, adapt
from app.domain.constants import BodyRegion
from app.domain.records import e1rm, new_personal_record
from app.domain.rounding import round_half_up

ADAPTING_PLAN_STATUSES = frozenset({"draft", "active"})


# ---------------------------------------------------------------- input


@dataclass(frozen=True)
class SetIn:
    set_number: int
    reps: int
    weight: Decimal
    completed: bool
    rpe: int | None


@dataclass(frozen=True)
class ExerciseIn:
    exercise_id: int
    session_exercise_id: int | None
    sort_order: int
    sets: tuple[SetIn, ...]


@dataclass(frozen=True)
class WorkoutIn:
    client_uuid: uuid.UUID | None
    training_session_id: int | None
    log_date: date
    rpe_rating: int
    exercises: tuple[ExerciseIn, ...]


# ---------------------------------------------------------------- stored data


@dataclass(frozen=True)
class PlannedRow:
    """A `session_exercise` of the logged session, with what adaptation needs."""

    id: int
    exercise_id: int
    sets: int
    reps: int
    weight: Decimal | None
    is_bodyweight: bool
    region: BodyRegion


@dataclass(frozen=True)
class SessionPlan:
    plan_status: str
    rows: tuple[PlannedRow, ...]


@dataclass(frozen=True)
class SetView:
    set_number: int
    reps: int
    weight: Decimal
    completed: bool
    rpe: int | None


@dataclass(frozen=True)
class ExerciseView:
    exercise_id: int
    exercise_name: str
    session_exercise_id: int | None
    sort_order: int
    sets: tuple[SetView, ...]


@dataclass(frozen=True)
class WorkoutView:
    id: int
    user_id: int
    training_session_id: int | None
    log_date: date
    rpe_rating: int | None
    logged_at: datetime
    deleted: bool
    exercises: tuple[ExerciseView, ...]


@dataclass(frozen=True)
class AdjustmentView:
    session_exercise_id: int
    reason: str
    old_sets: int
    new_sets: int
    old_reps: int
    new_reps: int
    old_weight: Decimal | None
    new_weight: Decimal | None


@dataclass(frozen=True)
class RecordView:
    id: int
    exercise_id: int
    max_weight: Decimal
    max_reps: int
    achieved_date: date


@dataclass(frozen=True)
class WorkoutResult:
    workout: WorkoutView
    adjustments: tuple[AdjustmentView, ...]
    new_personal_records: tuple[RecordView, ...]


class WorkoutStore(Protocol):
    """Every call of one `WorkoutUnitOfWork` runs in the same transaction."""

    async def find_by_client_uuid(self, client_uuid: uuid.UUID) -> WorkoutView | None: ...

    async def lock_session_plan(
        self, user_id: int, training_session_id: int
    ) -> SessionPlan | None: ...

    async def exercise_names(self, exercise_ids: set[int]) -> dict[int, str]: ...

    async def insert_workout(
        self, user_id: int, workout: WorkoutIn, session_exercise_ids: list[int | None]
    ) -> int: ...

    async def replace_workout(
        self,
        user_id: int,
        workout_id: int,
        workout: WorkoutIn,
        session_exercise_ids: list[int | None],
    ) -> bool: ...

    async def apply_adjustment(
        self, workout_id: int, row: PlannedRow, adjustment: Adjustment
    ) -> None: ...

    async def current_record(
        self, user_id: int, exercise_id: int
    ) -> tuple[Decimal, int] | None: ...

    async def replace_record(
        self,
        user_id: int,
        exercise_id: int,
        weight: Decimal,
        reps: int,
        estimated_1rm: Decimal,
        achieved: date,
    ) -> int: ...

    async def notify_achievement(self, user_id: int, message: str, data: dict) -> None: ...

    async def result(self, user_id: int, workout_id: int) -> WorkoutResult | None: ...

    async def list_workouts(
        self, user_id: int, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[int, list[WorkoutView]]: ...

    async def soft_delete(self, user_id: int, workout_id: int) -> bool: ...


WorkoutUnitOfWork = Callable[[], AbstractAsyncContextManager[WorkoutStore]]


class ClientUuidTakenError(Exception):
    """The insert hit the unique `client_uuid` (a concurrent replay or another user)."""


# ---------------------------------------------------------------- service


def _invalid(field: str, code: str, message: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed",
        [{"field": field, "code": code, "message": message}],
    )


def _check_input(workout: WorkoutIn, timezone: str, now: datetime) -> None:
    tomorrow = now.astimezone(ZoneInfo(timezone)).date() + timedelta(days=1)
    if workout.log_date > tomorrow:
        raise _invalid("body.log_date", "future_date", "Date is after tomorrow")
    seen: set[tuple[int, int]] = set()
    for i, exercise in enumerate(workout.exercises):
        for j, logged in enumerate(exercise.sets):
            key = (exercise.exercise_id, logged.set_number)
            if key in seen:
                raise _invalid(
                    f"body.exercises.{i}.sets.{j}.set_number",
                    "duplicate",
                    "Set number repeats for this exercise",
                )
            seen.add(key)


def _match(workout: WorkoutIn, plan: SessionPlan | None) -> list[PlannedRow | None]:
    """By `session_exercise_id`, else by `exercise_id` within the session."""
    rows = {row.id: row for row in plan.rows} if plan else {}
    used: set[int] = set()
    matched: list[PlannedRow | None] = []
    for i, exercise in enumerate(workout.exercises):
        row = None
        if exercise.session_exercise_id is not None:
            row = rows.get(exercise.session_exercise_id)
            if row is None or row.id in used:
                raise _invalid(
                    f"body.exercises.{i}.session_exercise_id",
                    "outside_session",
                    "Not a planned exercise of this session",
                )
        elif plan:
            row = next(
                (
                    r
                    for r in plan.rows
                    if r.exercise_id == exercise.exercise_id and r.id not in used
                ),
                None,
            )
        if row is not None:
            used.add(row.id)
        matched.append(row)
    return matched


def _logged(exercise: ExerciseIn) -> list[LoggedSet]:
    return [LoggedSet(s.reps, s.weight, s.completed, s.rpe) for s in exercise.sets]


class WorkoutService:
    def __init__(self, unit_of_work: WorkoutUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def create(
        self, user_id: int, timezone: str, workout: WorkoutIn, now: datetime
    ) -> WorkoutResult:
        _check_input(workout, timezone, now)
        try:
            async with self._unit_of_work() as store:
                return await self._create(store, user_id, workout)
        except ClientUuidTakenError:
            # lost a race with the same client_uuid: answer like a replay
            async with self._unit_of_work() as store:
                return await self._replay(store, user_id, workout)

    async def _replay(self, store: WorkoutStore, user_id: int, workout: WorkoutIn):
        existing = await store.find_by_client_uuid(workout.client_uuid)
        if existing is None or existing.user_id != user_id or existing.deleted:
            raise AppError(409, ErrorCode.CONFLICT, "client_uuid is already used")
        return await store.result(user_id, existing.id)

    async def _resolve(self, store: WorkoutStore, user_id: int, workout: WorkoutIn):
        """Known exercises, the user's session (locked) and the planned rows they match."""
        ids = {exercise.exercise_id for exercise in workout.exercises}
        names = await store.exercise_names(ids)
        for i, exercise in enumerate(workout.exercises):
            if exercise.exercise_id not in names:
                raise _invalid(f"body.exercises.{i}.exercise_id", "not_found", "Unknown exercise")

        plan = None
        if workout.training_session_id is not None:
            plan = await store.lock_session_plan(user_id, workout.training_session_id)
            if plan is None:  # unknown, or another user's: the same answer
                raise _invalid("body.training_session_id", "not_found", "Unknown session")
        elif any(e.session_exercise_id is not None for e in workout.exercises):
            raise _invalid(
                "body.training_session_id",
                "missing",
                "session_exercise_id needs a training_session_id",
            )
        matched = _match(workout, plan)

        return names, plan, matched

    async def _create(self, store: WorkoutStore, user_id: int, workout: WorkoutIn):
        if workout.client_uuid is not None and await store.find_by_client_uuid(workout.client_uuid):
            return await self._replay(store, user_id, workout)

        names, plan, matched = await self._resolve(store, user_id, workout)
        workout_id = await store.insert_workout(
            user_id, workout, [row.id if row else None for row in matched]
        )

        # algorithms.md 6: only for a draft or active plan; no signal, no change
        if plan is not None and plan.plan_status in ADAPTING_PLAN_STATUSES:
            for exercise, row in zip(workout.exercises, matched, strict=True):
                if row is None:
                    continue
                planned = PlannedExercise(
                    row.sets, row.reps, row.weight, row.is_bodyweight, row.region
                )
                adjustment = adapt(planned, _logged(exercise), workout.rpe_rating)
                if adjustment is not None:
                    await store.apply_adjustment(workout_id, row, adjustment)

        for exercise_id in dict.fromkeys(e.exercise_id for e in workout.exercises):
            sets = [
                s for e in workout.exercises if e.exercise_id == exercise_id for s in _logged(e)
            ]
            current = await store.current_record(user_id, exercise_id)
            record = new_personal_record(sets, current)
            if record is None:
                continue
            estimated = round_half_up(e1rm(record.weight_kg, record.reps), 2)
            record_id = await store.replace_record(
                user_id, exercise_id, record.weight_kg, record.reps, estimated, workout.log_date
            )
            await store.notify_achievement(
                user_id,
                f"New personal record: {names[exercise_id]}, "
                f"{record.weight_kg.normalize():f} kg x {record.reps}",
                {
                    "workout_log_id": workout_id,
                    "personal_record_id": record_id,
                    "exercise_id": exercise_id,
                },
            )

        return await store.result(user_id, workout_id)

    async def update(
        self, user_id: int, timezone: str, workout_id: int, workout: WorkoutIn, now: datetime
    ) -> WorkoutView:
        """Keeps the client_uuid, does not adapt the plan, does not recompute records."""
        _check_input(workout, timezone, now)
        async with self._unit_of_work() as store:
            _, _, matched = await self._resolve(store, user_id, workout)
            replaced = await store.replace_workout(
                user_id, workout_id, workout, [row.id if row else None for row in matched]
            )
            if not replaced:
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
            return (await store.result(user_id, workout_id)).workout

    async def list(
        self, user_id: int, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[int, list[WorkoutView]]:
        async with self._unit_of_work() as store:
            return await store.list_workouts(user_id, date_from, date_to, limit, offset)

    async def delete(self, user_id: int, workout_id: int) -> None:
        async with self._unit_of_work() as store:
            if not await store.soft_delete(user_id, workout_id):
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
