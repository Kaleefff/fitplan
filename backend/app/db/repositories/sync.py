"""Sync change queries: pull by cursor with tombstones, row state for push (DB-13; NFR-OFF,
D10, api-rules.md "Sync").

The synced kinds are the three log tables, named as the OpenAPI `SyncEntity`; plans are
not synced. A change is a row of one of them whose `updated_at` is after the cursor: a
create, an edit, or a soft delete (a tombstone, `deleted_at` set, no data). Every write of
such a row is an UPDATE or INSERT that sets `updated_at` (trigger `set_updated_at`, and the
repositories always UPDATE the parent row when only its children change).

Order is (updated_at, kind, id), kinds in plain string order. `updated_at` is the start
of the writing transaction (`now()`), so a row can become visible after rows with a later
`updated_at`; the cursor of the last page therefore goes back to the database's
`now() - 60 s`, and the next pull sends again what changed in that minute (the client
applies changes idempotently). A writing transaction longer than 60 s may be missed.

One `SqlSyncStore` lives in one transaction (`SqlSyncUnitOfWork`). Every query filters by
the user. The store does not validate `limit` (the API takes 1-100).
"""

import base64
import json
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, literal_column, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BodyMetrics, NutritionLog, WorkoutLog
from app.db.repositories.body_metrics import _view as metrics_view
from app.db.repositories.nutrition_logs import NutritionLogView, SqlNutritionLogStore
from app.db.repositories.workouts import SqlWorkoutStore
from app.services.body_metrics import MetricsView
from app.services.workouts import WorkoutView

BODY_METRICS, NUTRITION_LOG, WORKOUT = "body_metrics", "nutrition_log", "workout"
TABLES: dict[str, type[BodyMetrics | NutritionLog | WorkoutLog]] = {
    BODY_METRICS: BodyMetrics,
    NUTRITION_LOG: NutritionLog,
    WORKOUT: WorkoutLog,
}
KINDS = tuple(sorted(TABLES))  # the order of kinds within one updated_at
OVERLAP = timedelta(seconds=60)  # the last page's cursor is the database's now() - OVERLAP
MAX_ID = 2**31 - 1  # ids are INTEGER

_BASE64URL = re.compile(r"[A-Za-z0-9_-]*")

# ---------------------------------------------------------------- data


class InvalidCursorError(Exception):
    """The cursor was not made by `encode_cursor` (the API answers 422)."""


@dataclass(frozen=True)
class SyncCursor:
    """The key of the last change sent. `kind` is "" (before every kind) and `id` 0 on the
    cursor of a last page."""

    updated_at: datetime
    kind: str
    id: int


@dataclass(frozen=True)
class SyncChange:
    entity: str  # one of KINDS
    id: int
    client_uuid: uuid.UUID
    updated_at: datetime
    deleted_at: datetime | None
    # the view the GET endpoints return; None for a tombstone
    data: WorkoutView | NutritionLogView | MetricsView | None


@dataclass(frozen=True)
class SyncPage:
    changes: tuple[SyncChange, ...]
    next_cursor: SyncCursor
    has_more: bool


@dataclass(frozen=True)
class SyncRowState:
    id: int
    updated_at: datetime
    deleted_at: datetime | None


# ---------------------------------------------------------------- cursor


def encode_cursor(cursor: SyncCursor) -> str:
    """Opaque base64url (no padding) of {"t": UTC time with microseconds, "k", "i"}."""
    if cursor.updated_at.utcoffset() is None:
        raise ValueError("cursor time without a time zone")
    payload = {
        "t": cursor.updated_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "k": cursor.kind,
        "i": cursor.id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(text: str) -> SyncCursor:
    """Raises InvalidCursorError for anything `encode_cursor` does not make: bad base64 or
    JSON, other keys, an unknown kind, a time without a time zone, an id out of range."""
    if not _BASE64URL.fullmatch(text):
        raise InvalidCursorError
    try:
        payload = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except ValueError:  # binascii.Error, UnicodeDecodeError, JSONDecodeError
        raise InvalidCursorError from None
    if not isinstance(payload, dict) or payload.keys() != {"t", "k", "i"}:
        raise InvalidCursorError
    moment, kind, row_id = payload["t"], payload["k"], payload["i"]
    if not isinstance(moment, str) or kind not in ("", *KINDS):
        raise InvalidCursorError
    if type(row_id) is not int or not 0 <= row_id <= MAX_ID:  # bool is not an id
        raise InvalidCursorError
    try:
        updated_at = datetime.fromisoformat(moment)
    except ValueError:
        raise InvalidCursorError from None
    if updated_at.utcoffset() is None:
        raise InvalidCursorError
    return SyncCursor(updated_at.astimezone(UTC), kind, row_id)


# ---------------------------------------------------------------- store


def _branch(kind: str, user_id: int, cursor: SyncCursor | None, limit: int | None) -> Select:
    """One kind's rows after the cursor, in (updated_at, id) order: a range of
    ix_<table>_user_updated. Rows of a kind after the cursor's kind are after the cursor
    from its time on, rows of a kind before it only after its time."""
    table = TABLES[kind]
    conditions = [table.user_id == user_id]
    if cursor is not None:
        if kind > cursor.kind:
            conditions.append(table.updated_at >= cursor.updated_at)
        elif kind < cursor.kind:
            conditions.append(table.updated_at > cursor.updated_at)
        else:
            conditions.append(
                tuple_(table.updated_at, table.id) > tuple_(cursor.updated_at, cursor.id)
            )
    return (
        select(
            # a constant from KINDS; the three names differ in their first letter, so
            # every collation orders them as Python does
            literal_column(f"'{kind}'").label("kind"),
            table.id,
            table.client_uuid,
            table.updated_at,
            table.deleted_at,
        )
        .where(*conditions)
        .order_by(table.updated_at, table.id)
        .limit(limit)
    )


class SqlSyncStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def changes_since(self, user_id: int, cursor: SyncCursor | None, limit: int) -> SyncPage:
        """At most `limit` changes after `cursor` (None: from the beginning), tombstones
        included. The number of statements does not grow with `limit`: one for the keys,
        one batch per kind for the data of live rows, one for the clock on a last page."""
        changes = union_all(*(_branch(kind, user_id, cursor, limit + 1) for kind in KINDS))
        changes = changes.subquery("changes")
        rows = (
            await self._session.execute(
                select(changes)
                .order_by(changes.c.updated_at, changes.c.kind, changes.c.id)
                .limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        data = await self._data(
            {
                kind: [r.id for r in rows if r.kind == kind and r.deleted_at is None]
                for kind in KINDS
            }
        )
        page = tuple(
            SyncChange(
                entity=r.kind,
                id=r.id,
                client_uuid=r.client_uuid,
                updated_at=r.updated_at,
                deleted_at=r.deleted_at,
                data=None if r.deleted_at is not None else data[r.kind, r.id],
            )
            for r in rows
            # skip, not raise: READ COMMITTED, the account may be deleted after the page query
            if r.deleted_at is not None or (r.kind, r.id) in data
        )
        if has_more:
            last = rows[-1]
            next_cursor = SyncCursor(last.updated_at, last.kind, last.id)
        else:  # the database clock, never the app's; same transaction as the page
            overlap_start = await self._session.scalar(select(func.now() - OVERLAP))
            next_cursor = SyncCursor(overlap_start, "", 0)
        return SyncPage(page, next_cursor, has_more)

    async def _data(self, live: dict[str, list[int]]) -> dict[tuple[str, int], object]:
        """The GET views of the live rows, one batch per kind: (kind, id) -> view."""
        data: dict[tuple[str, int], object] = {}
        if live[WORKOUT]:
            logs = await self._rows(WorkoutLog, live[WORKOUT])
            for view in await SqlWorkoutStore(self._session)._views(logs):
                data[WORKOUT, view.id] = view
        if live[NUTRITION_LOG]:
            logs = await self._rows(NutritionLog, live[NUTRITION_LOG])
            for view in await SqlNutritionLogStore(self._session)._views(logs):
                data[NUTRITION_LOG, view.id] = view
        if live[BODY_METRICS]:
            for row in await self._rows(BodyMetrics, live[BODY_METRICS]):
                data[BODY_METRICS, row.id] = metrics_view(row)
        return data

    async def _rows(self, table, ids: Sequence[int]) -> list:
        return list(
            await self._session.scalars(
                select(table)
                .where(table.id.in_(ids))
                .order_by(table.id)
                .execution_options(populate_existing=True)
            )
        )

    async def lookup(
        self, user_id: int, entity: str, client_uuid: uuid.UUID
    ) -> SyncRowState | None:
        """The row of the user's `client_uuid` (a tombstone too), locked FOR UPDATE until
        the end of the transaction: push checks base_updated_at and "a deleted item stays
        deleted" against it. None for an unknown uuid and for another user's row."""
        table = TABLES.get(entity)
        if table is None:
            raise ValueError(f"not a synced entity: {entity!r}")
        row = (
            await self._session.execute(
                select(table.id, table.updated_at, table.deleted_at)
                .where(table.user_id == user_id, table.client_uuid == client_uuid)
                .with_for_update()
            )
        ).first()
        return None if row is None else SyncRowState(row.id, row.updated_at, row.deleted_at)


class SqlSyncUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlSyncStore]:
        async with self._sessions.begin() as session:
            yield SqlSyncStore(session)
