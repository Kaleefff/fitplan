"""`body_metrics` and the profile weight it feeds: `BodyMetricsStore` (B-17)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppUser, BodyMetrics, UserProfile
from app.db.repositories.profile_data import SqlProfileStore
from app.services.body_metrics import MEASURES, MetricsIn, MetricsView
from app.services.profile import ProfileView


def _view(row: BodyMetrics) -> MetricsView:
    return MetricsView(
        **{name: getattr(row, name) for name in MEASURES},
        id=row.id,
        user_id=row.user_id,
        client_uuid=row.client_uuid,
        recorded_at=row.recorded_at,
        deleted=row.deleted_at is not None,
    )


class SqlBodyMetricsStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_user(self, user_id: int) -> None:
        await self._session.execute(
            select(AppUser.id).where(AppUser.id == user_id).with_for_update()
        )

    async def _one(self, *conditions) -> MetricsView | None:
        row = await self._session.scalar(
            select(BodyMetrics).where(*conditions).execution_options(populate_existing=True)
        )
        return None if row is None else _view(row)

    async def by_client_uuid(self, client_uuid: uuid.UUID) -> MetricsView | None:
        return await self._one(BodyMetrics.client_uuid == client_uuid)

    async def live_on(self, user_id: int, day: date) -> MetricsView | None:
        return await self._one(
            BodyMetrics.user_id == user_id,
            BodyMetrics.measured_on == day,
            BodyMetrics.deleted_at.is_(None),
        )

    async def get(self, user_id: int, metrics_id: int) -> MetricsView | None:
        return await self._one(BodyMetrics.id == metrics_id, BodyMetrics.user_id == user_id)

    async def newest(self, user_id: int) -> MetricsView | None:
        row = await self._session.scalar(
            select(BodyMetrics)
            .where(BodyMetrics.user_id == user_id, BodyMetrics.deleted_at.is_(None))
            .order_by(BodyMetrics.measured_on.desc(), BodyMetrics.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _view(row)

    async def insert(self, user_id: int, values: MetricsIn, client_uuid: uuid.UUID | None) -> int:
        row = BodyMetrics(user_id=user_id, **{name: getattr(values, name) for name in MEASURES})
        if client_uuid is not None:
            row.client_uuid = client_uuid
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def replace(
        self, metrics_id: int, values: MetricsIn, client_uuid: uuid.UUID | None
    ) -> None:
        changes = {name: getattr(values, name) for name in MEASURES}
        if client_uuid is not None:
            changes["client_uuid"] = client_uuid
        await self._session.execute(
            update(BodyMetrics).where(BodyMetrics.id == metrics_id).values(**changes)
        )

    async def soft_delete(self, metrics_id: int) -> None:
        await self._session.execute(
            update(BodyMetrics).where(BodyMetrics.id == metrics_id).values(deleted_at=func.now())
        )

    async def history(
        self, user_id: int, date_from: date | None, date_to: date | None
    ) -> list[MetricsView]:
        query = select(BodyMetrics).where(
            BodyMetrics.user_id == user_id, BodyMetrics.deleted_at.is_(None)
        )
        if date_from is not None:
            query = query.where(BodyMetrics.measured_on >= date_from)
        if date_to is not None:
            query = query.where(BodyMetrics.measured_on <= date_to)
        rows = await self._session.scalars(
            query.order_by(BodyMetrics.measured_on.desc(), BodyMetrics.id.desc())
        )
        return [_view(row) for row in rows]

    async def profile(self, user_id: int) -> ProfileView | None:
        return await SqlProfileStore(self._session).get_profile(user_id)

    async def set_profile_weight(self, user_id: int, weight: Decimal, tdee_kcal: int) -> None:
        # profile_update stays the user's own last edit
        await self._session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(current_weight=weight, tdee=tdee_kcal)
        )


class SqlBodyMetricsUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlBodyMetricsStore]:
        async with self._sessions.begin() as session:
            yield SqlBodyMetricsStore(session)
