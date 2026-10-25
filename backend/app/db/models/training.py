"""Module 3: training plan, exercise library, injuries and workout logs.

The view workout_log_summary is created by the baseline migration and has no model.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    FetchedValue,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import NOW, TIMESTAMPTZ, Base
from app.db.enums import (
    ADJUSTMENT_REASON,
    BODY_REGION,
    DIFFICULTY_LEVEL,
    EQUIPMENT_TYPE,
    GOAL_TYPE,
    INJURY_SEVERITY,
    PLAN_STATUS,
    AdjustmentReason,
    BodyRegion,
    DifficultyLevel,
    EquipmentType,
    GoalType,
    InjurySeverity,
    PlanStatus,
)


class MuscleGroup(Base):
    __tablename__ = "muscle_group"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    group_name: Mapped[str] = mapped_column(String(45), unique=True)
    region: Mapped[BodyRegion] = mapped_column(BODY_REGION)
    description: Mapped[str] = mapped_column(String(250))
    image_url: Mapped[str | None] = mapped_column(String(250))


class Exercise(Base):
    __tablename__ = "exercise"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    difficulty_level: Mapped[DifficultyLevel] = mapped_column(DIFFICULTY_LEVEL)
    equipment: Mapped[EquipmentType] = mapped_column(EQUIPMENT_TYPE)
    is_compound: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_bodyweight: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    description: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str] = mapped_column(Text)


class ExerciseMuscleGroup(Base):
    __tablename__ = "exercise_muscle_group"
    __table_args__ = (
        Index("ix_exercise_muscle_group_muscle_group_id", "muscle_group_id"),
        Index(
            "ux_exercise_muscle_group_one_primary",
            "exercise_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True
    )
    muscle_group_id: Mapped[int] = mapped_column(
        ForeignKey("muscle_group.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class InjuryType(Base):
    __tablename__ = "injury_type"
    __table_args__ = (CheckConstraint("avg_healing_time_days > 0"),)

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    type_name: Mapped[str] = mapped_column(String(45), unique=True)
    description: Mapped[str] = mapped_column(String(250))
    avg_healing_time_days: Mapped[int] = mapped_column(SmallInteger)


class InjuryTypeExcludedExercise(Base):
    __tablename__ = "injury_type_excluded_exercise"
    __table_args__ = (Index("ix_injury_type_excluded_exercise_exercise_id", "exercise_id"),)

    injury_type_id: Mapped[int] = mapped_column(
        ForeignKey("injury_type.id", ondelete="CASCADE"), primary_key=True
    )
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True
    )


class Injury(Base):
    __tablename__ = "injury"
    __table_args__ = (
        Index("ix_injury_user_id", "user_id"),
        Index("ix_injury_injury_type_id", "injury_type_id"),
        Index("ix_injury_affected_muscle_group_id", "affected_muscle_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    injury_type_id: Mapped[int] = mapped_column(ForeignKey("injury_type.id"))
    affected_muscle_group_id: Mapped[int] = mapped_column(ForeignKey("muscle_group.id"))
    severity: Mapped[InjurySeverity] = mapped_column(INJURY_SEVERITY)
    start_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class TrainingPlan(Base):
    __tablename__ = "training_plan"
    __table_args__ = (
        CheckConstraint("num_training_days BETWEEN 1 AND 7"),
        CheckConstraint("end_date >= start_date", name="training_plan_check"),
        CheckConstraint(
            "status = 'draft' OR (start_date IS NOT NULL AND end_date IS NOT NULL)",
            name="training_plan_check1",
        ),
        Index("ix_training_plan_user_id", "user_id"),
        Index(
            "ux_training_plan_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ux_training_plan_one_draft",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    plan_name: Mapped[str] = mapped_column(String(45))
    goal: Mapped[GoalType] = mapped_column(GOAL_TYPE)
    num_training_days: Mapped[int] = mapped_column(SmallInteger)
    experience_level: Mapped[DifficultyLevel] = mapped_column(DIFFICULTY_LEVEL)
    equipment: Mapped[EquipmentType] = mapped_column(EQUIPMENT_TYPE)
    skipped_muscle_group_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'")
    )
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[PlanStatus] = mapped_column(PLAN_STATUS, server_default=text("'draft'"))


class TrainingSession(Base):
    __tablename__ = "training_session"
    __table_args__ = (
        CheckConstraint("session_order > 0"),
        CheckConstraint("day_of_week BETWEEN 1 AND 7"),
        CheckConstraint("estimated_duration > 0"),
        UniqueConstraint("training_plan_id", "session_order"),
        UniqueConstraint("training_plan_id", "day_of_week"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(
        ForeignKey("training_plan.id", ondelete="CASCADE")
    )
    session_order: Mapped[int] = mapped_column(SmallInteger)
    session_name: Mapped[str] = mapped_column(String(30))
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    estimated_duration: Mapped[int] = mapped_column(SmallInteger)


class SessionExercise(Base):
    __tablename__ = "session_exercise"
    __table_args__ = (
        CheckConstraint("sort_order > 0"),
        CheckConstraint("planned_sets > 0"),
        CheckConstraint("planned_reps > 0"),
        CheckConstraint("planned_weight >= 0"),
        CheckConstraint("rest_seconds >= 0"),
        UniqueConstraint("training_session_id", "sort_order"),
        Index("ix_session_exercise_exercise_id", "exercise_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_session.id", ondelete="CASCADE")
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    original_exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercise.id"))
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    planned_sets: Mapped[int] = mapped_column(SmallInteger)
    planned_reps: Mapped[int] = mapped_column(SmallInteger)
    planned_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    rest_seconds: Mapped[int] = mapped_column(SmallInteger)


class WorkoutLog(Base):
    __tablename__ = "workout_log"
    __table_args__ = (
        CheckConstraint("rpe_rating BETWEEN 1 AND 10"),
        Index("ix_workout_log_user_date", "user_id", "log_date"),
        Index("ix_workout_log_training_session_id", "training_session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    client_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, server_default=text("gen_random_uuid()")
    )
    training_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_session.id", ondelete="SET NULL")
    )
    log_date: Mapped[date] = mapped_column(Date)
    rpe_rating: Mapped[int | None] = mapped_column(SmallInteger)
    logged_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=NOW, server_onupdate=FetchedValue()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class WorkoutLogExercise(Base):
    __tablename__ = "workout_log_exercise"
    __table_args__ = (
        CheckConstraint("sort_order > 0"),
        UniqueConstraint("workout_log_id", "sort_order"),
        Index("ix_workout_log_exercise_exercise_id", "exercise_id"),
        Index("ix_workout_log_exercise_session_exercise_id", "session_exercise_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    workout_log_id: Mapped[int] = mapped_column(ForeignKey("workout_log.id", ondelete="CASCADE"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    session_exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("session_exercise.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class WorkoutSet(Base):
    __tablename__ = "workout_set"
    __table_args__ = (
        CheckConstraint("set_number > 0"),
        CheckConstraint("reps >= 0"),
        CheckConstraint("weight >= 0"),
        CheckConstraint("rpe BETWEEN 1 AND 10"),
        UniqueConstraint("workout_log_exercise_id", "set_number"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    workout_log_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("workout_log_exercise.id", ondelete="CASCADE")
    )
    set_number: Mapped[int] = mapped_column(SmallInteger)
    reps: Mapped[int] = mapped_column(SmallInteger)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    completed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    rpe: Mapped[int | None] = mapped_column(SmallInteger)


class PlanAdjustment(Base):
    __tablename__ = "plan_adjustment"
    __table_args__ = (
        CheckConstraint("old_sets > 0"),
        CheckConstraint("new_sets > 0"),
        CheckConstraint("old_reps > 0"),
        CheckConstraint("new_reps > 0"),
        CheckConstraint("old_weight >= 0"),
        CheckConstraint("new_weight >= 0"),
        Index("ix_plan_adjustment_session_exercise_id", "session_exercise_id"),
        Index("ix_plan_adjustment_workout_log_id", "workout_log_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    session_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("session_exercise.id", ondelete="CASCADE")
    )
    workout_log_id: Mapped[int] = mapped_column(ForeignKey("workout_log.id", ondelete="CASCADE"))
    reason: Mapped[AdjustmentReason] = mapped_column(ADJUSTMENT_REASON)
    old_sets: Mapped[int] = mapped_column(SmallInteger)
    new_sets: Mapped[int] = mapped_column(SmallInteger)
    old_reps: Mapped[int] = mapped_column(SmallInteger)
    new_reps: Mapped[int] = mapped_column(SmallInteger)
    old_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    new_weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class PersonalRecord(Base):
    __tablename__ = "personal_record"
    __table_args__ = (
        CheckConstraint("max_weight >= 0"),
        CheckConstraint("max_reps > 0"),
        CheckConstraint("e1rm >= 0"),
        Index("ix_personal_record_exercise_id", "exercise_id"),
        Index(
            "ux_personal_record_one_current",
            "user_id",
            "exercise_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercise.id"))
    max_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    max_reps: Mapped[int] = mapped_column(SmallInteger)
    e1rm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    achieved_date: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
