"""Nutrition logs and the daily summary (B-21; FR-A3, FR-R2; api-rules.md "Logs").

Storage and the macro arithmetic are DB-09's (`app.db.repositories.nutrition_logs`);
this module checks dates in the user's time zone and turns the store's errors into
the contract's error body.
"""

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.core.errors import AppError, ErrorCode
from app.db.repositories.nutrition_logs import (
    ClientUuidDeletedError,
    DailySummaryView,
    DuplicateFoodError,
    ItemError,
    ItemIn,
    LogTooLargeError,
    NutritionLogIn,
    NutritionLogView,
    UnknownFoodError,
    UnknownPlannedMealError,
    ZeroGramsError,
)


class NutritionLogStore(Protocol):
    """Every call of one unit of work runs in the same transaction."""

    async def create(self, user_id: int, log: NutritionLogIn) -> NutritionLogView: ...

    async def get(self, user_id: int, log_id: int) -> NutritionLogView | None: ...

    async def list_logs(
        self, user_id: int, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[int, list[NutritionLogView]]: ...

    async def update(
        self,
        user_id: int,
        log_id: int,
        changes: Mapping[str, object],
        items: Sequence[ItemIn] | None,
    ) -> NutritionLogView | None: ...

    async def soft_delete(self, user_id: int, log_id: int) -> bool: ...

    async def daily_summary(self, user_id: int, day: date) -> DailySummaryView: ...


NutritionLogUnitOfWork = Callable[[], AbstractAsyncContextManager[NutritionLogStore]]


def _invalid(field: str, code: str, message: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed",
        [{"field": field, "code": code, "message": message}],
    )


def _not_found() -> AppError:
    return AppError(404, ErrorCode.NOT_FOUND, "Not found")


StoreError = (ItemError, LogTooLargeError, UnknownPlannedMealError, ClientUuidDeletedError)


def _store_error(error: Exception) -> AppError:
    """DB-09's errors as the contract's error body (create and update)."""
    at = f"body.items.{getattr(error, 'index', 0)}"
    if isinstance(error, DuplicateFoodError):
        return _invalid(f"{at}.food_item_id", "duplicate", "The food is already in the log")
    if isinstance(error, UnknownFoodError):
        return _invalid(f"{at}.food_item_id", "not_found", "Unknown or inactive food")
    if isinstance(error, ZeroGramsError):
        return _invalid(f"{at}.grams", "invalid_value", "Grams round to 0.0")
    if isinstance(error, LogTooLargeError):
        return _invalid("body.items", "too_large", "A total of the log is above 9999.99")
    if isinstance(error, UnknownPlannedMealError):
        return _invalid("body.planned_meal_id", "not_found", "Not a meal of the user's diet plans")
    message = "client_uuid belongs to a deleted log"
    return AppError(
        409,
        ErrorCode.CONFLICT,
        message,
        [{"field": "body.client_uuid", "code": "conflict", "message": message}],
    )


def today(timezone: str, now: datetime) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def _check_date(log_date: date | None, timezone: str, now: datetime) -> None:
    if log_date is not None and log_date > today(timezone, now) + timedelta(days=1):
        raise _invalid("body.log_date", "future_date", "Date is after tomorrow")


class NutritionLogService:
    def __init__(self, unit_of_work: NutritionLogUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def create(
        self, user_id: int, log: NutritionLogIn, timezone: str, now: datetime
    ) -> NutritionLogView:
        """A repeated client_uuid returns the first log (api-rules.md Logs)."""
        _check_date(log.log_date, timezone, now)
        try:
            async with self._unit_of_work() as store:
                return await store.create(user_id, log)
        except StoreError as error:
            raise _store_error(error) from None

    async def list_logs(
        self, user_id: int, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[int, list[NutritionLogView]]:
        async with self._unit_of_work() as store:
            return await store.list_logs(user_id, date_from, date_to, limit, offset)

    async def update(
        self,
        user_id: int,
        log_id: int,
        changes: Mapping[str, object],
        items: Sequence[ItemIn] | None,
        timezone: str,
        now: datetime,
    ) -> NutritionLogView:
        _check_date(changes.get("log_date"), timezone, now)
        try:
            async with self._unit_of_work() as store:
                updated = await store.update(user_id, log_id, changes, items)
        except StoreError as error:
            raise _store_error(error) from None
        if updated is None:
            raise _not_found()
        return updated

    async def delete(self, user_id: int, log_id: int) -> None:
        async with self._unit_of_work() as store:
            if not await store.soft_delete(user_id, log_id):
                raise _not_found()

    async def daily_summary(self, user_id: int, day: date) -> DailySummaryView:
        async with self._unit_of_work() as store:
            return await store.daily_summary(user_id, day)
