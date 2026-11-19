"""Progress reports: generate, list, detail (B-25; FR-R1, FR-R5).

A report holds the analytics of its period (`algorithms.md` 8) and the goal prediction
as of the generation day (`api-rules.md` "Reports"). Fewer than 7 days of history is
422 `insufficient_data`; another user's report is 404.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.domain import analytics
from app.domain.reports import ReportFigures, period_problems, report_figures
from app.services.analytics import AnalyticsUnitOfWork, prediction_as_of, today_in


@dataclass(frozen=True)
class ReportView:
    id: int
    figures: ReportFigures
    is_auto: bool  # made by the weekly job (FR-R7, stretch)
    generated_at: datetime


class ReportStore(Protocol):
    async def save(self, user_id: int, figures: ReportFigures, now: datetime) -> ReportView:
        """Inserts, or replaces the user's report of the same period."""
        ...

    async def list_reports(
        self, user_id: int, limit: int, offset: int
    ) -> tuple[int, list[ReportView]]: ...

    async def get(self, user_id: int, report_id: int) -> ReportView | None: ...


class ReportService:
    def __init__(self, analytics_unit_of_work: AnalyticsUnitOfWork, store: ReportStore) -> None:
        self._analytics = analytics_unit_of_work
        self._store = store

    async def generate(
        self, user_id: int, start: date, end: date, timezone: str, now: datetime
    ) -> ReportView:
        today = today_in(timezone, now)
        problems = period_problems(start, end, today)
        if problems:
            raise AppError(422, ErrorCode.VALIDATION_ERROR, "Invalid report period", problems)
        async with self._analytics() as store:
            # TODO(questions.md [DB-10, B-23] record_days counts records dated tomorrow)
            if not analytics.enough_history(await store.record_days(user_id)):
                raise AppError(
                    422,
                    ErrorCode.INSUFFICIENT_DATA,
                    "Reports need at least 7 days of data (FR-R5)",
                )
            # TODO(questions.md [B-25]): compliance uses the active plan, as analytics does;
            # a past period whose plan has been archived gets null compliance
            data = await store.data(user_id, start, end)
            prediction = await prediction_as_of(store, user_id, today)
        return await self._store.save(user_id, report_figures(start, end, data, prediction), now)

    async def list_reports(
        self, user_id: int, limit: int, offset: int
    ) -> tuple[int, list[ReportView]]:
        return await self._store.list_reports(user_id, limit, offset)

    async def get(self, user_id: int, report_id: int) -> ReportView:
        report = await self._store.get(user_id, report_id)
        if report is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
        return report
