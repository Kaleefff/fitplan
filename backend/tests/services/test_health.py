"""DependencyHealthChecker against unreachable stores; no Docker needed."""

import asyncio

from pymongo import AsyncMongoClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.session import database_url
from app.services.health import DependencyHealthChecker

# port 1 is never served, so both connections fail at once
UNREACHABLE = Settings(postgres_port=1, mongo_port=1, health_check_timeout_seconds=0.5)


def test_unreachable_stores_are_down():
    async def check():
        engine = create_async_engine(database_url(UNREACHABLE))
        mongo = AsyncMongoClient(**UNREACHABLE.mongo_client_kwargs(), serverSelectionTimeoutMS=500)
        try:
            return await DependencyHealthChecker(UNREACHABLE, engine, mongo).check()
        finally:
            await mongo.close()
            await engine.dispose()

    report = asyncio.run(check())

    assert (report.postgres, report.mongo, report.status) == ("down", "down", "degraded")
