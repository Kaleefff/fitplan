"""Body measurements (B-17; FR-R1 data, FR-U6; api-rules.md "Logs").

One live measurement per day; saving again for the day replaces it (fields not sent
become null); the same client_uuid may move it to another free day. The newest live
measurement is copied to the profile weight and TDEE is recomputed; a backdated one
leaves the profile alone; deleting the newest restores the previous one.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.core.errors import AppError, ErrorCode
from app.domain.nutrition import bmr, tdee
from app.services.profile import ProfileView


@dataclass(frozen=True)
class MetricsIn:
    measured_on: date
    weight: Decimal
    chest: Decimal | None = None
    waist: Decimal | None = None
    thigh: Decimal | None = None
    bicep: Decimal | None = None
    hip: Decimal | None = None
    calf: Decimal | None = None
    fat_percentage: Decimal | None = None


MEASURES = tuple(f.name for f in fields(MetricsIn))


@dataclass(frozen=True)
class MetricsView(MetricsIn):
    id: int = 0
    user_id: int = 0
    client_uuid: uuid.UUID | None = None
    recorded_at: datetime | None = None
    deleted: bool = False

    def same_values(self, other: MetricsIn) -> bool:
        return all(getattr(self, name) == getattr(other, name) for name in MEASURES)


class BodyMetricsStore(Protocol):
    """Every call of one unit of work runs in the same transaction."""

    async def lock_user(self, user_id: int) -> None: ...

    async def by_client_uuid(self, client_uuid: uuid.UUID) -> MetricsView | None: ...

    async def live_on(self, user_id: int, day: date) -> MetricsView | None: ...

    async def get(self, user_id: int, metrics_id: int) -> MetricsView | None: ...

    async def newest(self, user_id: int) -> MetricsView | None: ...

    async def insert(
        self, user_id: int, values: MetricsIn, client_uuid: uuid.UUID | None
    ) -> int: ...

    async def replace(
        self, metrics_id: int, values: MetricsIn, client_uuid: uuid.UUID | None
    ) -> None: ...

    async def soft_delete(self, metrics_id: int) -> None: ...

    async def history(
        self, user_id: int, date_from: date | None, date_to: date | None
    ) -> list[MetricsView]: ...

    async def profile(self, user_id: int) -> ProfileView | None: ...

    async def set_profile_weight(self, user_id: int, weight: Decimal, tdee_kcal: int) -> None: ...


BodyMetricsUnitOfWork = Callable[[], AbstractAsyncContextManager[BodyMetricsStore]]


def _conflict(message: str, field: str) -> AppError:
    return AppError(
        409, ErrorCode.CONFLICT, message, [{"field": field, "code": "conflict", "message": message}]
    )


class BodyMetricsService:
    def __init__(self, unit_of_work: BodyMetricsUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def save(
        self,
        user_id: int,
        values: MetricsIn,
        client_uuid: uuid.UUID | None,
        timezone: str,
        now: datetime,
    ) -> MetricsView:
        tomorrow = now.astimezone(ZoneInfo(timezone)).date() + timedelta(days=1)
        if values.measured_on > tomorrow:
            raise AppError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                [{"field": "body.measured_on", "code": "future_date", "message": "After tomorrow"}],
            )
        async with self._unit_of_work() as store:
            await store.lock_user(user_id)  # one writer per user: one live row per day
            newest_before = await store.newest(user_id)
            target = None
            if client_uuid is not None:
                target = await store.by_client_uuid(client_uuid)
                if target is not None and (target.user_id != user_id or target.deleted):
                    raise _conflict("client_uuid is already used", "body.client_uuid")
                if target is not None and target.same_values(values):
                    return target  # a repeat: nothing is applied twice
            day = await store.live_on(user_id, values.measured_on)
            if target is not None:
                if day is not None and day.id != target.id:
                    raise _conflict("Another measurement exists on that day", "body.measured_on")
                await store.replace(target.id, values, client_uuid)
                saved_id = target.id
            elif day is not None:
                await store.replace(day.id, values, client_uuid or day.client_uuid)
                saved_id = day.id
            else:
                saved_id = await store.insert(user_id, values, client_uuid)
            await self._sync_profile(store, user_id, newest_before, saved_id)
            return await store.get(user_id, saved_id)

    async def delete(self, user_id: int, metrics_id: int) -> None:
        async with self._unit_of_work() as store:
            await store.lock_user(user_id)
            row = await store.get(user_id, metrics_id)
            if row is None or row.deleted:
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
            newest_before = await store.newest(user_id)
            await store.soft_delete(metrics_id)
            await self._sync_profile(store, user_id, newest_before, metrics_id)

    async def history(
        self, user_id: int, date_from: date | None, date_to: date | None
    ) -> list[MetricsView]:
        async with self._unit_of_work() as store:
            return await store.history(user_id, date_from, date_to)

    async def _sync_profile(
        self, store: BodyMetricsStore, user_id: int, newest_before: MetricsView | None, changed: int
    ) -> None:
        """Only a change that touches the newest measurement reaches the profile."""
        newest = await store.newest(user_id)
        was_newest = newest_before is not None and newest_before.id == changed
        is_newest = newest is not None and newest.id == changed
        if not (was_newest or is_newest) or newest is None:
            return
        profile = await store.profile(user_id)
        if profile is None:  # no profile yet: nothing to keep in step
            return
        energy = tdee(
            bmr(profile.sex, newest.weight, Decimal(profile.height), profile.age),
            profile.activity_level_pal,
        )
        await store.set_profile_weight(user_id, newest.weight, energy)
