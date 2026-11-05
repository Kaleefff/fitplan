"""Analytics endpoints (B-23; FR-R1 to FR-R5): the domain math of algorithms.md 7-9 over
the user's rows, in the user's time zone."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain import analytics
from app.domain.constants import PREDICTION_WINDOW_DAYS
from app.domain.prediction import GoalPrediction, predict_goal


class AnalyticsStore(Protocol):
    async def record_days(self, user_id: int) -> int: ...

    async def data(self, user_id: int, start: date, end: date) -> analytics.AnalyticsData: ...

    async def target_weight(self, user_id: int) -> Decimal | None: ...


AnalyticsUnitOfWork = Callable[[], AbstractAsyncContextManager[AnalyticsStore]]


def _today(timezone: str, now: datetime) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


class AnalyticsService:
    def __init__(self, unit_of_work: AnalyticsUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def summary(
        self, user_id: int, period: str, timezone: str, now: datetime
    ) -> analytics.Summary:
        today = _today(timezone, now)
        start, end = analytics.window(period, today)
        async with self._unit_of_work() as store:
            record_days = await store.record_days(user_id)
            data = await store.data(user_id, start, end)
        return analytics.summary(period, today, record_days, data)

    async def chart(
        self, user_id: int, metric: str, period: str, timezone: str, now: datetime
    ) -> tuple[str, list[tuple[date, float]]]:
        start, end = analytics.window(period, _today(timezone, now))
        async with self._unit_of_work() as store:
            if not analytics.enough_history(await store.record_days(user_id)):
                return "insufficient_data", []
            data = await store.data(user_id, start, end)
        return "ok", analytics.series(metric, data, start, end)

    async def goal_prediction(self, user_id: int, timezone: str, now: datetime) -> GoalPrediction:
        """algorithms.md 9: weigh-ins and workout compliance of the last 28 days."""
        today = _today(timezone, now)
        start = today - timedelta(days=PREDICTION_WINDOW_DAYS - 1)
        async with self._unit_of_work() as store:
            target = await store.target_weight(user_id)
            data = await store.data(user_id, start, today)
        compliance = analytics.training_compliance(data.workouts, data.training_plan, start, today)
        return predict_goal(data.weigh_ins, target, today, compliance)
