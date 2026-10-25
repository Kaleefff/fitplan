"""Token pairs with refresh rotation and reuse detection (B-02, api-rules.md "Auth and account").

- Every refresh token belongs to a family that starts at login. Refreshing revokes the
  presented token, links it to its successor and issues a fresh 30-day token (sliding).
- Presenting a revoked token again (reuse) revokes the whole family: either the client
  or an attacker holds a stolen copy, so both must log in again.
- Logout revokes the family of the caller's own token, even an already rotated one.
  An unknown token, or one of another user, is 401 and revokes nothing.
- Access tokens stay valid until they expire (no deny list).

Storage is the `RefreshToken` model (`app/db/models/user.py`); DATA implements the repository.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core.config import Settings
from app.core.security import create_access_token, hash_opaque_token, new_opaque_token


@dataclass(frozen=True)
class RefreshTokenRecord:
    id: int
    user_id: int
    family_id: uuid.UUID
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    replaced_by_id: int | None


class RefreshTokenRepository(Protocol):
    async def add(
        self,
        *,
        user_id: int,
        family_id: uuid.UUID,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRecord: ...

    async def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None: ...

    async def replace(self, token_id: int, *, replaced_by_id: int, revoked_at: datetime) -> bool:
        """Revokes a live token and links its successor; False if it was already revoked."""
        ...

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None: ...

    async def revoke_user(self, user_id: int, revoked_at: datetime) -> None: ...


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class InvalidRefreshTokenError(Exception):
    """Unknown, expired, revoked or foreign refresh token (401 `unauthorized`)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TokenService:
    def __init__(
        self,
        settings: Settings,
        repository: RefreshTokenRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._clock = clock

    async def issue_pair(self, user_id: int) -> TokenPair:
        """After login or registration: a new family."""
        pair, _ = await self._issue(user_id, uuid.uuid4(), self._clock())
        return pair

    async def rotate(self, refresh_token: str) -> TokenPair:
        now = self._clock()
        record = await self._repository.get_by_hash(hash_opaque_token(refresh_token))
        if record is None or record.expires_at <= now:
            raise InvalidRefreshTokenError
        if record.revoked_at is not None:
            await self._repository.revoke_family(record.family_id, now)
            raise InvalidRefreshTokenError
        pair, successor = await self._issue(record.user_id, record.family_id, now)
        # Two concurrent refreshes with the same token: only one may win, the other is reuse.
        if not await self._repository.replace(
            record.id, replaced_by_id=successor.id, revoked_at=now
        ):
            await self._repository.revoke_family(record.family_id, now)
            raise InvalidRefreshTokenError
        return pair

    async def logout(self, refresh_token: str, user_id: int) -> None:
        record = await self._repository.get_by_hash(hash_opaque_token(refresh_token))
        if record is None or record.user_id != user_id:
            raise InvalidRefreshTokenError
        await self._repository.revoke_family(record.family_id, self._clock())

    async def revoke_all(self, user_id: int) -> None:
        """Password change or reset."""
        await self._repository.revoke_user(user_id, self._clock())

    async def _issue(
        self, user_id: int, family_id: uuid.UUID, now: datetime
    ) -> tuple[TokenPair, RefreshTokenRecord]:
        refresh_token = new_opaque_token()
        record = await self._repository.add(
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_opaque_token(refresh_token),
            issued_at=now,
            expires_at=now + timedelta(days=self._settings.refresh_token_days),
        )
        lifetime = timedelta(minutes=self._settings.access_token_minutes)
        access_token = create_access_token(user_id, self._settings.jwt_signing_key(), lifetime, now)
        pair = TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(lifetime.total_seconds()),
        )
        return pair, record
