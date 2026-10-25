"""Dependency checks for GET /health, through the shared engine of `app.db.session`."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from pymongo import AsyncMongoClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

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
    def __init__(
        self, settings: Settings, engine: AsyncEngine, mongo_client: AsyncMongoClient
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._mongo = mongo_client

    async def check(self) -> HealthReport:
        postgres, mongo = await asyncio.gather(self._check_postgres(), self._check_mongo())
        return HealthReport(postgres=postgres, mongo=mongo, version=self._settings.app_version)

    async def _check_postgres(self) -> DependencyStatus:
        try:
            async with (
                asyncio.timeout(self._settings.health_check_timeout_seconds),
                self._engine.connect() as conn,
            ):
                await conn.execute(text("SELECT 1"))
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
