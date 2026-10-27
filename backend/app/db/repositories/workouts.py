"""Workout logs, plan adjustments, personal records: `app.services.workouts.WorkoutStore`.

One `SqlWorkoutStore` lives in one transaction (`SqlWorkoutUnitOfWork`), so a workout
and everything it changes commit together.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import AdjustmentReason, NotificationType
from app.db.models import (
    Exercise,
    ExerciseMuscleGroup,
    MuscleGroup,
    Notification,
    PersonalRecord,
    PlanAdjustment,
    SessionExercise,
    TrainingPlan,
    TrainingSession,
    WorkoutLog,
    WorkoutLogExercise,
    WorkoutSet,
)
from app.domain.adaptation import Adjustment
from app.domain.constants import BodyRegion
from app.services.workouts import (
    AdjustmentView,
    ClientUuidTakenError,
    ExerciseView,
    PlannedRow,
    RecordView,
    SessionPlan,
    SetView,
    WorkoutIn,
    WorkoutResult,
    WorkoutView,
)

CLIENT_UUID_CONSTRAINT = "workout_log_client_uuid_key"


class SqlWorkoutStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_client_uuid(self, client_uuid: uuid.UUID) -> WorkoutView | None:
        log = await self._session.scalar(
            select(WorkoutLog).where(WorkoutLog.client_uuid == client_uuid)
        )
        return None if log is None else await self._view(log)

    async def lock_session_plan(self, user_id: int, training_session_id: int) -> SessionPlan | None:
        status = await self._session.scalar(
            select(TrainingPlan.status)
            .join(TrainingSession, TrainingSession.training_plan_id == TrainingPlan.id)
            .where(TrainingSession.id == training_session_id, TrainingPlan.user_id == user_id)
        )
        if status is None:
            return None
        # FOR UPDATE: two workouts of the same session never adapt from the same base
        rows = await self._session.execute(
            select(SessionExercise, Exercise.is_bodyweight, MuscleGroup.region)
            .join(Exercise, Exercise.id == SessionExercise.exercise_id)
            .join(
                ExerciseMuscleGroup,
                (ExerciseMuscleGroup.exercise_id == Exercise.id) & ExerciseMuscleGroup.is_primary,
            )
            .join(MuscleGroup, MuscleGroup.id == ExerciseMuscleGroup.muscle_group_id)
            .where(SessionExercise.training_session_id == training_session_id)
            .order_by(SessionExercise.sort_order)
            .with_for_update(of=SessionExercise)
        )
        return SessionPlan(
            plan_status=status.value,
            rows=tuple(
                PlannedRow(
                    id=row.id,
                    exercise_id=row.exercise_id,
                    sets=row.planned_sets,
                    reps=row.planned_reps,
                    weight=row.planned_weight,
                    is_bodyweight=is_bodyweight,
                    region=BodyRegion(region.value),
                )
                for row, is_bodyweight, region in rows
            ),
        )

    async def exercise_names(self, exercise_ids: set[int]) -> dict[int, str]:
        rows = await self._session.execute(
            select(Exercise.id, Exercise.name).where(Exercise.id.in_(exercise_ids))
        )
        return {exercise_id: name for exercise_id, name in rows}

    async def insert_workout(
        self, user_id: int, workout: WorkoutIn, session_exercise_ids: list[int | None]
    ) -> int:
        log = WorkoutLog(
            user_id=user_id,
            training_session_id=workout.training_session_id,
            log_date=workout.log_date,
            rpe_rating=workout.rpe_rating,
        )
        if workout.client_uuid is not None:
            log.client_uuid = workout.client_uuid
        self._session.add(log)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig.diag, "constraint_name", None) == CLIENT_UUID_CONSTRAINT:
                raise ClientUuidTakenError from None
            raise
        await self._insert_exercises(log.id, workout, session_exercise_ids)
        await self._session.flush()
        return log.id

    async def replace_workout(
        self,
        user_id: int,
        workout_id: int,
        workout: WorkoutIn,
        session_exercise_ids: list[int | None],
    ) -> bool:
        """PUT: same row and client_uuid, new fields and exercises; nothing is adapted."""
        log = await self._session.scalar(
            select(WorkoutLog)
            .where(
                WorkoutLog.id == workout_id,
                WorkoutLog.user_id == user_id,
                WorkoutLog.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if log is None:
            return False
        log.training_session_id = workout.training_session_id
        log.log_date = workout.log_date
        log.rpe_rating = workout.rpe_rating
        await self._session.execute(
            delete(WorkoutLogExercise).where(WorkoutLogExercise.workout_log_id == workout_id)
        )
        await self._insert_exercises(workout_id, workout, session_exercise_ids)
        await self._session.flush()
        return True

    async def _insert_exercises(
        self, workout_id: int, workout: WorkoutIn, session_exercise_ids: list[int | None]
    ) -> None:
        for exercise, session_exercise_id in zip(
            workout.exercises, session_exercise_ids, strict=True
        ):
            logged = WorkoutLogExercise(
                workout_log_id=workout_id,
                exercise_id=exercise.exercise_id,
                session_exercise_id=session_exercise_id,
                sort_order=exercise.sort_order,
            )
            self._session.add(logged)
            await self._session.flush()
            self._session.add_all(
                WorkoutSet(
                    workout_log_exercise_id=logged.id,
                    set_number=s.set_number,
                    reps=s.reps,
                    weight=s.weight,
                    completed=s.completed,
                    rpe=s.rpe,
                )
                for s in exercise.sets
            )

    async def apply_adjustment(self, workout_id: int, row: PlannedRow, adjustment: Adjustment):
        await self._session.execute(
            update(SessionExercise)
            .where(SessionExercise.id == row.id)
            .values(
                planned_sets=adjustment.sets,
                planned_reps=adjustment.reps,
                planned_weight=adjustment.weight_kg,
            )
        )
        self._session.add(
            PlanAdjustment(
                session_exercise_id=row.id,
                workout_log_id=workout_id,
                reason=AdjustmentReason(adjustment.reason.value),
                old_sets=row.sets,
                new_sets=adjustment.sets,
                old_reps=row.reps,
                new_reps=adjustment.reps,
                old_weight=row.weight,
                new_weight=adjustment.weight_kg,
            )
        )
        await self._session.flush()

    async def current_record(self, user_id: int, exercise_id: int) -> tuple[Decimal, int] | None:
        row = await self._session.execute(
            select(PersonalRecord.max_weight, PersonalRecord.max_reps)
            .where(
                PersonalRecord.user_id == user_id,
                PersonalRecord.exercise_id == exercise_id,
                PersonalRecord.is_current,
            )
            .with_for_update()
        )
        found = row.first()
        return None if found is None else (found.max_weight, found.max_reps)

    async def replace_record(
        self,
        user_id: int,
        exercise_id: int,
        weight: Decimal,
        reps: int,
        estimated_1rm: Decimal,
        achieved: date,
    ) -> int:
        await self._session.execute(
            update(PersonalRecord)
            .where(
                PersonalRecord.user_id == user_id,
                PersonalRecord.exercise_id == exercise_id,
                PersonalRecord.is_current,
            )
            .values(is_current=False)
        )
        record = PersonalRecord(
            user_id=user_id,
            exercise_id=exercise_id,
            max_weight=weight,
            max_reps=reps,
            e1rm=estimated_1rm,
            achieved_date=achieved,
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def notify_achievement(self, user_id: int, message: str, data: dict) -> None:
        self._session.add(
            Notification(
                user_id=user_id,
                message_type=NotificationType.ACHIEVEMENT,
                scheduled_at=datetime.now(UTC),
                message=message,
                data=data,
            )
        )
        await self._session.flush()

    async def result(self, user_id: int, workout_id: int) -> WorkoutResult | None:
        log = await self._session.get(WorkoutLog, workout_id)
        if log is None or log.user_id != user_id:
            return None
        await self._session.refresh(log)  # server defaults (logged_at) after the insert
        adjustments = await self._session.scalars(
            select(PlanAdjustment)
            .where(PlanAdjustment.workout_log_id == workout_id)
            .order_by(PlanAdjustment.id)
        )
        # the records a workout created are named by its achievement notifications
        record_ids = select(Notification.data["personal_record_id"].as_integer()).where(
            Notification.user_id == user_id,
            Notification.message_type == NotificationType.ACHIEVEMENT,
            Notification.data["workout_log_id"].as_integer() == workout_id,
        )
        records = await self._session.scalars(
            select(PersonalRecord)
            .where(PersonalRecord.id.in_(record_ids))
            .order_by(PersonalRecord.id)
        )
        return WorkoutResult(
            workout=await self._view(log),
            adjustments=tuple(
                AdjustmentView(
                    session_exercise_id=a.session_exercise_id,
                    reason=a.reason.value,
                    old_sets=a.old_sets,
                    new_sets=a.new_sets,
                    old_reps=a.old_reps,
                    new_reps=a.new_reps,
                    old_weight=a.old_weight,
                    new_weight=a.new_weight,
                )
                for a in adjustments
            ),
            new_personal_records=tuple(
                RecordView(r.id, r.exercise_id, r.max_weight, r.max_reps, r.achieved_date)
                for r in records
            ),
        )

    async def list_workouts(
        self, user_id: int, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[int, list[WorkoutView]]:
        conditions = [WorkoutLog.user_id == user_id, WorkoutLog.deleted_at.is_(None)]
        if date_from is not None:
            conditions.append(WorkoutLog.log_date >= date_from)
        if date_to is not None:
            conditions.append(WorkoutLog.log_date <= date_to)
        total = await self._session.scalar(select(func.count()).where(*conditions))
        logs = await self._session.scalars(
            select(WorkoutLog)
            .where(*conditions)
            .order_by(WorkoutLog.log_date.desc(), WorkoutLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return total, [await self._view(log) for log in logs]

    async def soft_delete(self, user_id: int, workout_id: int) -> bool:
        result = await self._session.execute(
            update(WorkoutLog)
            .where(
                WorkoutLog.id == workout_id,
                WorkoutLog.user_id == user_id,
                WorkoutLog.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        return result.rowcount == 1

    async def _view(self, log: WorkoutLog) -> WorkoutView:
        rows = await self._session.execute(
            select(WorkoutLogExercise, Exercise.name)
            .join(Exercise, Exercise.id == WorkoutLogExercise.exercise_id)
            .where(WorkoutLogExercise.workout_log_id == log.id)
            .order_by(WorkoutLogExercise.sort_order)
        )
        exercises = []
        for logged, name in rows:
            sets = await self._session.scalars(
                select(WorkoutSet)
                .where(WorkoutSet.workout_log_exercise_id == logged.id)
                .order_by(WorkoutSet.set_number)
            )
            exercises.append(
                ExerciseView(
                    exercise_id=logged.exercise_id,
                    exercise_name=name,
                    session_exercise_id=logged.session_exercise_id,
                    sort_order=logged.sort_order,
                    sets=tuple(
                        SetView(s.set_number, s.reps, s.weight, s.completed, s.rpe) for s in sets
                    ),
                )
            )
        return WorkoutView(
            id=log.id,
            user_id=log.user_id,
            training_session_id=log.training_session_id,
            log_date=log.log_date,
            rpe_rating=log.rpe_rating,
            logged_at=log.logged_at,
            deleted=log.deleted_at is not None,
            exercises=tuple(exercises),
        )


class SqlWorkoutUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlWorkoutStore]:
        async with self._sessions.begin() as session:
            yield SqlWorkoutStore(session)
