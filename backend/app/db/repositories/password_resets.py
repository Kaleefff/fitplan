"""`password_reset_token`: single-use, hashed reset tokens (B-04, FR-U3)."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppUser, PasswordResetToken, RefreshToken


class SqlPasswordResetRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        async with self._sessions.begin() as session:
            session.add(
                PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
            )

    async def reset(self, token_hash: str, now: datetime, password_hash: str) -> int | None:
        """In one transaction: use the token (once, before it expires), set the password,
        end every other reset token and every session of the user. None if the token is
        unknown, used or expired."""
        async with self._sessions.begin() as session:
            user_id = await session.scalar(
                update(PasswordResetToken)
                .where(
                    PasswordResetToken.token_hash == token_hash,
                    PasswordResetToken.used_at.is_(None),
                    PasswordResetToken.expires_at > now,
                )
                .values(used_at=now)
                .returning(PasswordResetToken.user_id)
            )
            if user_id is None:
                return None
            await session.execute(
                update(AppUser).where(AppUser.id == user_id).values(password_hash=password_hash)
            )
            await session.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
                .values(used_at=now)
            )
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            return user_id
