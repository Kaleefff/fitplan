"""Reminders and notifications (B-14; FR-P9, FR-R7; api-rules.md "Reports and notifications").

The app proposes the reminders and saves the whole list with PUT; the server creates
none and never converts `time_of_day` (wall-clock time). Notifications are listed when
due, newest first (questions.md, D-03: proposed default).
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol

REMINDERS_MAX = 50


@dataclass(frozen=True)
class ReminderIn:
    message_type: str  # meal_reminder | training_reminder
    day_of_week: int | None  # None = every day
    time_of_day: time
    message: str
    is_enabled: bool


@dataclass(frozen=True)
class ReminderView(ReminderIn):
    id: int


@dataclass(frozen=True)
class NotificationView:
    id: int
    message_type: str
    scheduled_at: datetime
    message: str
    data: dict | None
    is_sent: bool
    sent_at: datetime | None
    is_dismissed: bool


class ScheduleStore(Protocol):
    async def reminders(self, user_id: int) -> list[ReminderView]: ...

    async def replace_reminders(self, user_id: int, reminders: list[ReminderIn]) -> None: ...

    async def notifications(
        self, user_id: int, due_by: datetime, limit: int, offset: int
    ) -> tuple[int, list[NotificationView]]: ...


ScheduleUnitOfWork = Callable[[], AbstractAsyncContextManager[ScheduleStore]]


class ScheduleService:
    def __init__(self, unit_of_work: ScheduleUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def reminders(self, user_id: int) -> list[ReminderView]:
        async with self._unit_of_work() as store:
            return await store.reminders(user_id)

    async def replace_reminders(
        self, user_id: int, reminders: list[ReminderIn]
    ) -> list[ReminderView]:
        async with self._unit_of_work() as store:
            await store.replace_reminders(user_id, reminders)
            return await store.reminders(user_id)

    async def notifications(
        self, user_id: int, now: datetime, limit: int, offset: int
    ) -> tuple[int, list[NotificationView]]:
        async with self._unit_of_work() as store:
            return await store.notifications(user_id, now, limit, offset)
