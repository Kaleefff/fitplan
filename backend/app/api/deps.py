from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import RateLimiter
from app.core.security import InvalidTokenError, decode_access_token
from app.services.auth import AuthService, UserRepository
from app.services.health import HealthChecker
from app.services.nutrition import ProfileReader
from app.services.training_plans import TrainingPlanService
from app.services.workouts import WorkoutService

# Same scheme name as the contract (`components.securitySchemes.bearerAuth`)
_bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False)


def get_health_checker(request: Request) -> HealthChecker:
    return request.app.state.health_checker


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_profile_reader(request: Request) -> ProfileReader:
    return request.app.state.profile_reader


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_user_repository(request: Request) -> UserRepository:
    return request.app.state.users


def get_workout_service(request: Request) -> WorkoutService:
    return request.app.state.workout_service


def get_training_plan_service(request: Request) -> TrainingPlanService:
    return request.app.state.training_plan_service


@dataclass(frozen=True)
class CurrentUser:
    id: int


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CurrentUser:
    if credentials is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Missing access token")
    try:
        user_id = decode_access_token(credentials.credentials, settings.jwt_signing_key())
    except InvalidTokenError:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Invalid or expired access token") from None
    return CurrentUser(id=user_id)


def auth_rate_limit(request: Request) -> None:
    """Dependency for register, login, forgot password and password-checking account routes."""
    limiter: RateLimiter = request.app.state.auth_rate_limiter
    client_ip = request.client.host if request.client else "unknown"
    retry_after = limiter.hit((client_ip, request.scope["route"].path))
    if retry_after is not None:
        raise AppError(
            429,
            ErrorCode.RATE_LIMITED,
            "Too many requests",
            headers={"Retry-After": str(retry_after)},
        )


class Owned(Protocol):
    user_id: int


def owned_or_404[OwnedT: Owned](row: OwnedT | None, user: CurrentUser) -> OwnedT:
    """Object-level authorization: another user's row looks exactly like a missing one."""
    if row is None or row.user_id != user.id:
        raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
    return row
