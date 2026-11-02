"""`reminder` and `notification`: `app.services.schedule.ScheduleStore` (B-14)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import NotificationType
from app.db.models import Notification, Reminder
from app.services.schedule import NotificationView, ReminderIn, ReminderView


class SqlScheduleStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reminders(self, user_id: int) -> list[ReminderView]:
        rows = await self._session.scalars(
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .order_by(Reminder.day_of_week.asc().nulls_first(), Reminder.time_of_day, Reminder.id)
        )
        return [
            ReminderView(
                id=r.id,
                message_type=r.message_type.value,
                day_of_week=r.day_of_week,
                time_of_day=r.time_of_day,
                message=r.message,
                is_enabled=r.is_enabled,
            )
            for r in rows
        ]

    async def replace_reminders(self, user_id: int, reminders: list[ReminderIn]) -> None:
        await self._session.execute(delete(Reminder).where(Reminder.user_id == user_id))
        self._session.add_all(
            Reminder(
                user_id=user_id,
                message_type=NotificationType(r.message_type),
                day_of_week=r.day_of_week,
                time_of_day=r.time_of_day,
                message=r.message,
                is_enabled=r.is_enabled,
            )
            for r in reminders
        )
        await self._session.flush()

    async def notifications(
        self, user_id: int, due_by: datetime, limit: int, offset: int
    ) -> tuple[int, list[NotificationView]]:
        conditions = (Notification.user_id == user_id, Notification.scheduled_at <= due_by)
        total = await self._session.scalar(select(func.count()).where(*conditions))
        rows = await self._session.scalars(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.scheduled_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return total, [
            NotificationView(
                id=n.id,
                message_type=n.message_type.value,
                scheduled_at=n.scheduled_at,
                message=n.message,
                data=n.data,
                is_sent=n.is_sent,
                sent_at=n.sent_at,
                is_dismissed=n.is_dismissed,
            )
            for n in rows
        ]


class SqlScheduleUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlScheduleStore]:
        async with self._sessions.begin() as session:
            yield SqlScheduleStore(session)
