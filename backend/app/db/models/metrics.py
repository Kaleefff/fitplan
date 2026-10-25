"""Module 4: body metrics and progress reports."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import NOW, TIMESTAMPTZ, Base
from app.db.enums import REPORT_TYPE, ReportType


class BodyMetrics(Base):
    __tablename__ = "body_metrics"
    __table_args__ = (
        CheckConstraint("weight BETWEEN 30 AND 300"),
        CheckConstraint("chest > 0"),
        CheckConstraint("waist > 0"),
        CheckConstraint("thigh > 0"),
        CheckConstraint("bicep > 0"),
        CheckConstraint("hip > 0"),
        CheckConstraint("calf > 0"),
        CheckConstraint("fat_percentage BETWEEN 0 AND 100"),
        Index(
            "ux_body_metrics_user_day_live",
            "user_id",
            "measured_on",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    measured_on: Mapped[date] = mapped_column(Date)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    chest: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    waist: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    thigh: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    bicep: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    hip: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    calf: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    fat_percentage: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    client_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, server_default=text("gen_random_uuid()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=NOW, server_onupdate=FetchedValue()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class ProgressReport(Base):
    __tablename__ = "progress_report"
    __table_args__ = (
        CheckConstraint("training_volume >= 0"),
        CheckConstraint("training_sessions_completed >= 0"),
        CheckConstraint("training_sessions_planned >= 0"),
        CheckConstraint("workout_compliance_pct >= 0"),
        CheckConstraint("diet_compliance_pct BETWEEN 0 AND 100"),
        CheckConstraint("avg_cals_daily >= 0"),
        CheckConstraint("report_period_end >= report_period_start", name="progress_report_check"),
        # Explicit name: the convention would exceed 63 characters; this is the
        # name PostgreSQL gave it in 01_schema.sql.
        UniqueConstraint(
            "user_id",
            "report_type",
            "report_period_start",
            "report_period_end",
            name="progress_report_user_id_report_type_report_period_start_rep_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    report_type: Mapped[ReportType] = mapped_column(REPORT_TYPE)
    report_period_start: Mapped[date] = mapped_column(Date)
    report_period_end: Mapped[date] = mapped_column(Date)
    weight_difference: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    training_volume: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    training_sessions_completed: Mapped[int] = mapped_column(SmallInteger)
    training_sessions_planned: Mapped[int] = mapped_column(SmallInteger)
    workout_compliance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    diet_compliance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    avg_cals_daily: Mapped[int | None] = mapped_column(Integer)
    key_lifts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    estimated_goal_completion_date: Mapped[date | None] = mapped_column(Date)
    irregular_data: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_auto: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
