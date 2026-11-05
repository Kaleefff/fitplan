"""Analytics queries (the DB-10/DB-11 part): rows for `app/domain/analytics.py` (B-23)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import PlanStatus
from app.db.models import (
    BodyMetrics,
    DietPlan,
    Exercise,
    NutritionLog,
    TrainingPlan,
    UserProfile,
    WorkoutLog,
    WorkoutLogExercise,
    WorkoutSet,
)
from app.domain.analytics import ActivePlan, AnalyticsData, LoggedSetRow


class SqlAnalyticsStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_days(self, user_id: int) -> int:
        """Distinct days with any live record: workout, nutrition log, measurement."""
        days = union(
            select(WorkoutLog.log_date).where(
                WorkoutLog.user_id == user_id, WorkoutLog.deleted_at.is_(None)
            ),
            select(NutritionLog.log_date).where(
                NutritionLog.user_id == user_id, NutritionLog.deleted_at.is_(None)
            ),
            select(BodyMetrics.measured_on).where(
                BodyMetrics.user_id == user_id, BodyMetrics.deleted_at.is_(None)
            ),
        ).subquery()
        return await self._session.scalar(select(func.count()).select_from(days))

    async def data(self, user_id: int, start: date, end: date) -> AnalyticsData:
        weigh_ins = (
            await self._session.execute(
                select(BodyMetrics.measured_on, BodyMetrics.weight)
                .where(
                    BodyMetrics.user_id == user_id,
                    BodyMetrics.deleted_at.is_(None),
                    BodyMetrics.measured_on.between(start, end),
                )
                .order_by(BodyMetrics.measured_on)
            )
        ).all()
        workouts = (
            await self._session.execute(
                select(WorkoutLog.id, WorkoutLog.log_date)
                .where(
                    WorkoutLog.user_id == user_id,
                    WorkoutLog.deleted_at.is_(None),
                    WorkoutLog.log_date.between(start, end),
                )
                .order_by(WorkoutLog.log_date, WorkoutLog.id)
            )
        ).all()
        sets = (
            await self._session.execute(
                select(
                    WorkoutLog.id,
                    WorkoutLog.log_date,
                    Exercise.id,
                    Exercise.name,
                    WorkoutSet.reps,
                    WorkoutSet.weight,
                    WorkoutSet.completed,
                )
                .join(WorkoutLogExercise, WorkoutLogExercise.workout_log_id == WorkoutLog.id)
                .join(Exercise, Exercise.id == WorkoutLogExercise.exercise_id)
                .join(WorkoutSet, WorkoutSet.workout_log_exercise_id == WorkoutLogExercise.id)
                .where(
                    WorkoutLog.user_id == user_id,
                    WorkoutLog.deleted_at.is_(None),
                    WorkoutLog.log_date.between(start, end),
                )
            )
        ).all()
        kcal = (
            await self._session.execute(
                select(NutritionLog.log_date, func.sum(NutritionLog.actual_cals))
                .where(
                    NutritionLog.user_id == user_id,
                    NutritionLog.deleted_at.is_(None),
                    NutritionLog.log_date.between(start, end),
                )
                .group_by(NutritionLog.log_date)
            )
        ).all()
        training = (
            await self._session.execute(
                select(
                    TrainingPlan.start_date, TrainingPlan.end_date, TrainingPlan.num_training_days
                ).where(TrainingPlan.user_id == user_id, TrainingPlan.status == PlanStatus.ACTIVE)
            )
        ).first()
        diet = (
            await self._session.execute(
                select(DietPlan.start_date, DietPlan.end_date, DietPlan.daily_cal_goal).where(
                    DietPlan.user_id == user_id, DietPlan.status == PlanStatus.ACTIVE
                )
            )
        ).first()
        return AnalyticsData(
            weigh_ins=[(day, weight) for day, weight in weigh_ins],
            workouts=[(workout_id, day) for workout_id, day in workouts],
            sets=[LoggedSetRow(*row) for row in sets],
            daily_kcal={day: total for day, total in kcal},
            training_plan=None
            if training is None
            else ActivePlan(training[0], training[1], sessions_per_week=training[2]),
            diet_plan=None if diet is None else ActivePlan(diet[0], diet[1], daily_kcal=diet[2]),
        )

    async def target_weight(self, user_id: int) -> Decimal | None:
        return await self._session.scalar(
            select(UserProfile.target_value).where(UserProfile.user_id == user_id)
        )


class SqlAnalyticsUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlAnalyticsStore]:
        async with self._sessions.begin() as session:
            yield SqlAnalyticsStore(session)
