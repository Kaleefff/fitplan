"""`app_user` (FR-U1, FR-U2)."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppUser

EMAIL_UNIQUE_CONSTRAINT = "app_user_email_key"


class EmailTakenError(Exception):
    """Another account already uses the email."""


@dataclass(frozen=True)
class UserRecord:
    id: int
    email: str
    password_hash: str | None  # None for social-only accounts
    name: str
    surname: str
    timezone: str
    registration_date: date


def _record(user: AppUser) -> UserRecord:
    return UserRecord(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        name=user.name,
        surname=user.surname,
        timezone=user.timezone,
        registration_date=user.registration_date,
    )


class SqlUserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(
        self, *, email: str, password_hash: str | None, name: str, surname: str
    ) -> UserRecord:
        async with self._sessions.begin() as session:
            user = AppUser(email=email, password_hash=password_hash, name=name, surname=surname)
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                if getattr(exc.orig.diag, "constraint_name", None) == EMAIL_UNIQUE_CONSTRAINT:
                    raise EmailTakenError from None
                raise
            await session.refresh(user)  # timezone and registration_date are server defaults
            return _record(user)

    async def get_by_email(self, email: str) -> UserRecord | None:
        async with self._sessions() as session:
            user = await session.scalar(select(AppUser).where(AppUser.email == email))
            return None if user is None else _record(user)

    async def get_by_id(self, user_id: int) -> UserRecord | None:
        async with self._sessions() as session:
            user = await session.get(AppUser, user_id)
            return None if user is None else _record(user)
