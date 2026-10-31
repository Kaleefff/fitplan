"""FastAPI application factory. Run: `uv run uvicorn app.main:app --reload`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pymongo import AsyncMongoClient

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import add_middleware
from app.core.rate_limit import RateLimiter
from app.db.session import get_async_engine
from app.services.auth import AuthService
from app.services.health import DependencyHealthChecker, HealthChecker
from app.services.profile import ProfileService
from app.services.repositories import Repositories, sql_repositories
from app.services.tokens import TokenService
from app.services.training_plans import TrainingPlanService
from app.services.workouts import WorkoutService

API_PREFIX = "/api/v1"
DOCS_URL = f"{API_PREFIX}/docs"


def create_app(
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
    repositories: Repositories | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repositories = repositories or sql_repositories()
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
        engine = get_async_engine()
        app.state.mongo = mongo
        app.state.health_checker = DependencyHealthChecker(settings, engine, mongo)
        try:
            yield
        finally:
            await mongo.close()
            await engine.dispose()

    app = FastAPI(
        title="FitPlan Pro API",
        version=settings.app_version,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=DOCS_URL,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.profile_reader = repositories.profiles
    app.state.users = repositories.users
    app.state.workout_service = WorkoutService(repositories.workouts)
    app.state.training_plan_service = TrainingPlanService(repositories.training_plans)
    app.state.profile_service = ProfileService(repositories.profile_data)
    app.state.auth_service = AuthService(
        settings, repositories.users, TokenService(settings, repositories.refresh_tokens)
    )
    app.state.auth_rate_limiter = RateLimiter(
        settings.auth_rate_limit, settings.auth_rate_window_seconds
    )
    register_error_handlers(app)
    add_middleware(app, settings, docs_path=DOCS_URL)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
