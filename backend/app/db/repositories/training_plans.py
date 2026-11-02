"""Training plans and the exercise catalogue: `app.services.training_plans.TrainingPlanStore`."""

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import DifficultyLevel as DbLevel
from app.db.enums import EquipmentType, GoalType, PlanStatus
from app.db.models import (
    AppUser,
    Exercise,
    ExerciseMuscleGroup,
    Injury,
    InjuryTypeExcludedExercise,
    MuscleGroup,
    SessionExercise,
    TrainingPlan,
    TrainingSession,
    WorkoutLog,
)
from app.domain.constants import DifficultyLevel, Equipment, InjurySeverity
from app.domain.training import ActiveInjury, ExerciseInfo, GeneratedPlan
from app.services.training_plans import (
    PlanRequest,
    PlanView,
    SessionExerciseView,
    SessionView,
)


class SqlTrainingPlanStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_user(self, user_id: int) -> None:
        await self._session.execute(
            select(AppUser.id).where(AppUser.id == user_id).with_for_update()
        )

    async def catalogue(self) -> list[ExerciseInfo]:
        groups = defaultdict(lambda: (None, set()))
        rows = await self._session.execute(
            select(
                ExerciseMuscleGroup.exercise_id,
                MuscleGroup.group_name,
                ExerciseMuscleGroup.is_primary,
            ).join(MuscleGroup, MuscleGroup.id == ExerciseMuscleGroup.muscle_group_id)
        )
        for exercise_id, group, is_primary in rows:
            primary, secondary = groups[exercise_id]
            groups[exercise_id] = (
                (group, secondary) if is_primary else (primary, secondary | {group})
            )
        excluded = defaultdict(set)
        for injury_type_id, exercise_id in await self._session.execute(
            select(
                InjuryTypeExcludedExercise.injury_type_id, InjuryTypeExcludedExercise.exercise_id
            )
        ):
            excluded[exercise_id].add(injury_type_id)
        exercises = await self._session.scalars(select(Exercise).order_by(Exercise.id))
        return [
            ExerciseInfo(
                id=e.id,
                difficulty_level=DifficultyLevel(e.difficulty_level.value),
                equipment=Equipment(e.equipment.value),
                is_compound=e.is_compound,
                primary_group=groups[e.id][0],
                secondary_groups=frozenset(groups[e.id][1]),
                excluded_for_injury_types=frozenset(excluded[e.id]),
            )
            for e in exercises
            if groups[e.id][0] is not None  # an exercise without a primary group is unusable
        ]

    async def active_injuries(self, user_id: int) -> list[ActiveInjury]:
        rows = await self._session.execute(
            select(Injury.injury_type_id, MuscleGroup.group_name, Injury.severity)
            .join(MuscleGroup, MuscleGroup.id == Injury.affected_muscle_group_id)
            .where(Injury.user_id == user_id, Injury.is_active)
        )
        return [
            ActiveInjury(type_id, group, InjurySeverity(severity.value))
            for type_id, group, severity in rows
        ]

    async def replace_draft(self, user_id: int, request: PlanRequest, plan: GeneratedPlan) -> int:
        await self._session.execute(
            delete(TrainingPlan).where(
                TrainingPlan.user_id == user_id, TrainingPlan.status == PlanStatus.DRAFT
            )
        )
        group_ids = dict(
            (
                await self._session.execute(
                    select(MuscleGroup.group_name, MuscleGroup.id).where(
                        MuscleGroup.group_name.in_(plan.skipped_groups)
                    )
                )
            ).all()
        )
        row = TrainingPlan(
            user_id=user_id,
            plan_name=plan.plan_name,
            goal=GoalType(request.goal.value),
            num_training_days=request.num_training_days,
            experience_level=DbLevel(request.experience_level.value),
            equipment=EquipmentType(request.equipment.value),
            skipped_muscle_group_ids=[group_ids[name] for name in plan.skipped_groups],
            status=PlanStatus.DRAFT,
        )
        self._session.add(row)
        await self._session.flush()
        for planned in plan.sessions:
            session = TrainingSession(
                training_plan_id=row.id,
                session_order=planned.session_order,
                session_name=planned.session_name,
                day_of_week=planned.day_of_week,
                estimated_duration=planned.estimated_duration,
            )
            self._session.add(session)
            await self._session.flush()
            self._session.add_all(
                SessionExercise(
                    training_session_id=session.id,
                    exercise_id=e.exercise_id,
                    sort_order=e.sort_order,
                    planned_sets=e.sets,
                    planned_reps=e.reps,
                    planned_weight=None,  # set by the baseline workout (algorithms.md 6)
                    rest_seconds=e.rest_seconds,
                )
                for e in planned.exercises
            )
        await self._session.flush()
        return row.id

    async def get_plan(self, user_id: int, plan_id: int) -> PlanView | None:
        plan = await self._session.scalar(
            select(TrainingPlan).where(TrainingPlan.id == plan_id, TrainingPlan.user_id == user_id)
        )
        return None if plan is None else await self._view(plan)

    async def get_active(self, user_id: int) -> PlanView | None:
        plan = await self._session.scalar(
            select(TrainingPlan).where(
                TrainingPlan.user_id == user_id, TrainingPlan.status == PlanStatus.ACTIVE
            )
        )
        return None if plan is None else await self._view(plan)

    async def activate(self, user_id: int, plan_id: int, start: date, end: date) -> None:
        # archive first: at most one active plan per user (ux_training_plan_one_active)
        await self._session.execute(
            update(TrainingPlan)
            .where(TrainingPlan.user_id == user_id, TrainingPlan.status == PlanStatus.ACTIVE)
            .values(status=PlanStatus.ARCHIVED)
        )
        await self._session.execute(
            update(TrainingPlan)
            .where(TrainingPlan.id == plan_id)
            .values(status=PlanStatus.ACTIVE, start_date=start, end_date=end)
        )

    async def workout_days(self, session_ids: list[int], since: date) -> set[tuple[int, date]]:
        rows = await self._session.execute(
            select(WorkoutLog.training_session_id, WorkoutLog.log_date).where(
                WorkoutLog.training_session_id.in_(session_ids),
                WorkoutLog.log_date >= since,
                WorkoutLog.deleted_at.is_(None),
            )
        )
        return {(session_id, day) for session_id, day in rows}

    async def _view(self, plan: TrainingPlan) -> PlanView:
        await self._session.refresh(plan)  # server defaults and the updates above
        skipped = (
            await self._session.scalars(
                select(MuscleGroup.group_name)
                .where(MuscleGroup.id.in_(plan.skipped_muscle_group_ids))
                .order_by(MuscleGroup.id)
            )
        ).all()
        sessions = (
            await self._session.scalars(
                select(TrainingSession)
                .where(TrainingSession.training_plan_id == plan.id)
                .order_by(TrainingSession.session_order)
            )
        ).all()
        rows = await self._session.execute(
            select(SessionExercise, Exercise.name)
            .join(Exercise, Exercise.id == SessionExercise.exercise_id)
            .where(SessionExercise.training_session_id.in_([s.id for s in sessions]))
            .order_by(SessionExercise.sort_order)
        )
        by_session = defaultdict(list)
        for row, name in rows:
            by_session[row.training_session_id].append(
                SessionExerciseView(
                    id=row.id,
                    exercise_id=row.exercise_id,
                    exercise_name=name,
                    sort_order=row.sort_order,
                    planned_sets=row.planned_sets,
                    planned_reps=row.planned_reps,
                    planned_weight=row.planned_weight,
                    rest_seconds=row.rest_seconds,
                )
            )
        return PlanView(
            id=plan.id,
            plan_name=plan.plan_name,
            goal=plan.goal.value,
            num_training_days=plan.num_training_days,
            experience_level=plan.experience_level.value,
            equipment=plan.equipment.value,
            generated_at=plan.generated_at,
            start_date=plan.start_date,
            end_date=plan.end_date,
            status=plan.status.value,
            skipped_muscle_groups=tuple(skipped),
            sessions=tuple(
                SessionView(
                    id=s.id,
                    session_order=s.session_order,
                    session_name=s.session_name,
                    day_of_week=s.day_of_week,
                    estimated_duration=s.estimated_duration,
                    exercises=tuple(by_session[s.id]),
                )
                for s in sessions
            ),
        )


class SqlTrainingPlanUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlTrainingPlanStore]:
        async with self._sessions.begin() as session:
            yield SqlTrainingPlanStore(session)
