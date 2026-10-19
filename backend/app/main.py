"""FastAPI application factory. Run: `uv run uvicorn app.main:app --reload`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pymongo import AsyncMongoClient

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.services.health import DependencyHealthChecker, HealthChecker

API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None, health_checker: HealthChecker | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if health_checker is not None:
            app.state.health_checker = health_checker
            yield
            return
        mongo = AsyncMongoClient(
            **settings.mongo_client_kwargs(),
            serverSelectionTimeoutMS=int(settings.health_check_timeout_seconds * 1000),
        )
        app.state.mongo = mongo
        app.state.health_checker = DependencyHealthChecker(settings, mongo)
        try:
            yield
        finally:
            await mongo.close()

    app = FastAPI(
        title="FitPlan Pro API",
        version=settings.app_version,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
