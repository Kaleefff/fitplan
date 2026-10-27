"""`refresh_token`: implements `app.services.tokens.RefreshTokenRepository` (B-02)."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RefreshToken
from app.services.tokens import RefreshTokenRecord


def _record(row: RefreshToken) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        id=row.id,
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=row.token_hash,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        replaced_by_id=row.replaced_by_id,
    )


class SqlRefreshTokenRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(
        self,
        *,
        user_id: int,
        family_id: uuid.UUID,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        async with self._sessions.begin() as session:
            row = RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=token_hash,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            session.add(row)
            await session.flush()
            return _record(row)

    async def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash)
            )
            return None if row is None else _record(row)

    async def replace(self, token_id: int, *, replaced_by_id: int, revoked_at: datetime) -> bool:
        """One UPDATE guarded by `revoked_at IS NULL`: of two concurrent refreshes, the
        second waits for the first's row lock, then matches nothing."""
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(RefreshToken)
                .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=revoked_at, replaced_by_id=replaced_by_id)
            )
            return result.rowcount == 1

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=revoked_at)
            )

    async def revoke_user(self, user_id: int, revoked_at: datetime) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=revoked_at)
            )
