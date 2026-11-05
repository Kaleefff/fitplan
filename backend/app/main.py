"""FastAPI application factory. Run: `uv run uvicorn app.main:app --reload`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.mail import MailSender, SmtpMailSender
from app.core.middleware import add_middleware
from app.core.rate_limit import RateLimiter
from app.db.repositories.meal_recognitions import MongoMealRecognitionRepository
from app.db.session import get_async_engine
from app.services.account import AccountService, RecognitionPurger
from app.services.analytics import AnalyticsService
from app.services.auth import AuthService
from app.services.body_metrics import BodyMetricsService
from app.services.diet_plans import DietPlanService
from app.services.health import DependencyHealthChecker, HealthChecker
from app.services.library import LibraryService
from app.services.password_reset import PasswordResetService
from app.services.profile import ProfileService
from app.services.repositories import Repositories, sql_repositories
from app.services.schedule import ScheduleService
from app.services.tokens import TokenService
from app.services.training_plans import TrainingPlanService
from app.services.workouts import WorkoutService

API_PREFIX = "/api/v1"
DOCS_URL = f"{API_PREFIX}/docs"

logger = logging.getLogger(__name__)


class _LifespanRecognitions:
    """The MongoDB buffer exists once the lifespan has opened its client (DB-07)."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def purge_user(self, user_id: int) -> int:
        buffer: RecognitionPurger | None = getattr(self._app.state, "recognitions", None)
        if buffer is None:
            raise RuntimeError("MongoDB recognition buffer is not available")
        return await buffer.purge_user(user_id)


def create_app(
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
    repositories: Repositories | None = None,
    mail_sender: MailSender | None = None,
    recognitions: RecognitionPurger | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    repositories = repositories or sql_repositories()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if health_checker is not None:
            app.state.health_checker = health_checker
            app.state.recognitions = recognitions
            yield
            return
        mongo = AsyncMongoClient(
            **settings.mongo_client_kwargs(),
            serverSelectionTimeoutMS=int(settings.health_check_timeout_seconds * 1000),
        )
        engine = get_async_engine()
        app.state.mongo = mongo
        app.state.health_checker = DependencyHealthChecker(settings, engine, mongo)
        buffer = MongoMealRecognitionRepository(mongo[settings.mongo_db])
        try:
            # the init script creates them only in compose; CI and fresh deployments need this
            await buffer.ensure_indexes()
        except PyMongoError as exc:  # start degraded like /health; reads still filter expiresAt
            logger.warning("MongoDB indexes not ensured: %s", type(exc).__name__)
        app.state.recognitions = recognitions or buffer
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
    app.state.body_metrics_service = BodyMetricsService(repositories.body_metrics)
    app.state.schedule_service = ScheduleService(repositories.schedule)
    app.state.diet_plan_service = DietPlanService(repositories.diet_plans)
    app.state.analytics_service = AnalyticsService(repositories.analytics)
    app.state.library_service = LibraryService(repositories.library, repositories.training_plans)
    app.state.account_service = AccountService(
        settings,
        repositories.users,
        TokenService(settings, repositories.refresh_tokens),
        _LifespanRecognitions(app),
    )
    app.state.password_reset_service = PasswordResetService(
        settings,
        repositories.users,
        repositories.password_resets,
        mail_sender or SmtpMailSender(settings),
    )
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
