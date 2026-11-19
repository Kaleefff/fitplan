"""Progress reports: `app.services.reports.ReportStore` (B-25; FR-R1). Written by API,
reviewed by DATA (D24).

Every query is scoped to the user. Generating the same period again replaces the stored
report (api-rules.md): an upsert on the unique (user, type, start, end) key keeps the id
and refreshes the figures and `generated_at`.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import ReportType as DbReportType
from app.db.models import ProgressReport
from app.domain.constants import ReportType
from app.domain.reports import ReportFigures, ReportKeyLift
from app.services.reports import ReportView

UNIQUE_PERIOD = "progress_report_user_id_report_type_report_period_start_rep_key"


def _view(row: ProgressReport) -> ReportView:
    figures = ReportFigures(
        report_type=ReportType(row.report_type.value),
        period_start=row.report_period_start,
        period_end=row.report_period_end,
        weight_difference=row.weight_difference,
        training_volume=row.training_volume,
        training_sessions_completed=row.training_sessions_completed,
        training_sessions_planned=row.training_sessions_planned,
        workout_compliance_pct=row.workout_compliance_pct,
        diet_compliance_pct=row.diet_compliance_pct,
        avg_cals_daily=row.avg_cals_daily,
        key_lifts=tuple(
            ReportKeyLift(
                k["exercise_id"],
                k["exercise_name"],
                Decimal(k["first_e1rm"]),
                Decimal(k["best_e1rm"]),
            )
            for k in row.key_lifts
        ),
        estimated_goal_completion_date=row.estimated_goal_completion_date,
        irregular_data=row.irregular_data,
    )
    return ReportView(row.id, figures, row.is_auto, row.generated_at)


class SqlReportStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, user_id: int, figures: ReportFigures, now: datetime) -> ReportView:
        values = {
            "weight_difference": figures.weight_difference,
            "training_volume": figures.training_volume,
            "training_sessions_completed": figures.training_sessions_completed,
            "training_sessions_planned": figures.training_sessions_planned,
            "workout_compliance_pct": figures.workout_compliance_pct,
            "diet_compliance_pct": figures.diet_compliance_pct,
            "avg_cals_daily": figures.avg_cals_daily,
            # JSON keeps the e1RM as a string, so no precision is lost
            "key_lifts": [
                {
                    "exercise_id": k.exercise_id,
                    "exercise_name": k.exercise_name,
                    "first_e1rm": str(k.first_e1rm),
                    "best_e1rm": str(k.best_e1rm),
                }
                for k in figures.key_lifts
            ],
            "estimated_goal_completion_date": figures.estimated_goal_completion_date,
            "irregular_data": figures.irregular_data,
            "is_auto": False,
            "generated_at": now,
        }
        statement = (
            insert(ProgressReport)
            .values(
                user_id=user_id,
                report_type=DbReportType(figures.report_type.value),
                report_period_start=figures.period_start,
                report_period_end=figures.period_end,
                **values,
            )
            .on_conflict_do_update(constraint=UNIQUE_PERIOD, set_=values)
            .returning(ProgressReport)
        )
        async with self._sessions.begin() as session:
            row = await session.scalar(statement, execution_options={"populate_existing": True})
            return _view(row)

    async def list_reports(
        self, user_id: int, limit: int, offset: int
    ) -> tuple[int, list[ReportView]]:
        """Newest first: by `generated_at`, then id."""
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(ProgressReport)
                .where(ProgressReport.user_id == user_id)
            )
            rows = await session.scalars(
                select(ProgressReport)
                .where(ProgressReport.user_id == user_id)
                .order_by(ProgressReport.generated_at.desc(), ProgressReport.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return total, [_view(row) for row in rows]

    async def get(self, user_id: int, report_id: int) -> ReportView | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ProgressReport).where(
                    ProgressReport.id == report_id, ProgressReport.user_id == user_id
                )
            )
            return None if row is None else _view(row)
