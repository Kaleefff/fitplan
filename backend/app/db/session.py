"""Engines and sessions (D17: psycopg 3, async in the API, sync in Alembic and scripts)."""

from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def database_url(settings: Settings | None = None) -> URL:
    """SQLAlchemy URL built from the same settings as the rest of the backend.

    URL.create escapes the password, so special characters in .env are safe.
    """
    settings = settings or get_settings()
    return URL.create(
        "postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


def create_sync_engine(url: URL | str | None = None) -> Engine:
    """Engine for Alembic, seed loaders and scripts."""
    return create_engine(url or database_url(), pool_pre_ping=True)


@lru_cache
def get_async_engine() -> AsyncEngine:
    """Process-wide engine for the API."""
    return create_async_engine(database_url(), pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)
