"""Dependency checks for GET /health.

PostgreSQL is checked with a short-lived psycopg connection, not through an
SQLAlchemy engine: the engine and sessions belong to DATA (`backend/app/db/`,
DB-01). Switch to the shared engine once it exists.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import psycopg
from pymongo import AsyncMongoClient

from app.core.config import Settings

logger = logging.getLogger(__name__)

DependencyStatus = Literal["ok", "down"]


@dataclass(frozen=True)
class HealthReport:
    postgres: DependencyStatus
    mongo: DependencyStatus
    version: str

    @property
    def status(self) -> Literal["ok", "degraded"]:
        return "ok" if self.postgres == "ok" and self.mongo == "ok" else "degraded"


class HealthChecker(Protocol):
    async def check(self) -> HealthReport: ...


class DependencyHealthChecker:
    def __init__(self, settings: Settings, mongo_client: AsyncMongoClient) -> None:
        self._settings = settings
        self._mongo = mongo_client

    async def check(self) -> HealthReport:
        postgres, mongo = await asyncio.gather(self._check_postgres(), self._check_mongo())
        return HealthReport(postgres=postgres, mongo=mongo, version=self._settings.app_version)

    async def _check_postgres(self) -> DependencyStatus:
        timeout = self._settings.health_check_timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                conn = await psycopg.AsyncConnection.connect(
                    self._settings.postgres_conninfo(), connect_timeout=max(1, int(timeout))
                )
                async with conn:
                    await conn.execute("SELECT 1")
        except Exception as exc:
            logger.warning("PostgreSQL health check failed: %s", type(exc).__name__)
            return "down"
        return "ok"

    async def _check_mongo(self) -> DependencyStatus:
        try:
            async with asyncio.timeout(self._settings.health_check_timeout_seconds):
                await self._mongo.admin.command("ping")
        except Exception as exc:
            logger.warning("MongoDB health check failed: %s", type(exc).__name__)
            return "down"
        return "ok"
