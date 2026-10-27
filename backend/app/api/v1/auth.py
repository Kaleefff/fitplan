from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import AfterValidator, BaseModel, EmailStr, StringConstraints

from app.api.deps import CurrentUser, auth_rate_limit, get_auth_service, get_current_user
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.core.security import password_policy_ok
from app.services.auth import AuthService
from app.services.tokens import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"], responses=VALIDATION_ERROR_RESPONSE)

EMAIL_MAX_LENGTH = 100  # app_user.email VARCHAR(100)


def _email_fits(email: str) -> str:
    if len(email) > EMAIL_MAX_LENGTH:
        raise ValueError(f"Email must be at most {EMAIL_MAX_LENGTH} characters")
    return email


def _password_ok(password: str) -> str:
    if not password_policy_ok(password):
        raise ValueError("Password must be 8-72 bytes with at least one letter and one digit")
    return password


Email = Annotated[EmailStr, AfterValidator(_email_fits)]
NewPassword = Annotated[str, AfterValidator(_password_ok)]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RegisterRequest(BaseModel):
    email: Email
    password: NewPassword
    name: PersonName
    surname: PersonName


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int

    @classmethod
    def of(cls, pair: TokenPair) -> "TokenPairOut":
        return cls(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            token_type="bearer",
            expires_in=pair.expires_in,
        )


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


Service = Annotated[AuthService, Depends(get_auth_service)]


@router.post(
    "/register",
    operation_id="register",
    summary="Register with email and password (FR-U1)",
    status_code=201,
    dependencies=[Depends(auth_rate_limit)],
    responses={409: _error("Email already registered"), 429: _error("Too many requests")},
)
async def register(body: RegisterRequest, service: Service) -> TokenPairOut:
    pair = await service.register(
        email=body.email, password=body.password, name=body.name, surname=body.surname
    )
    return TokenPairOut.of(pair)


@router.post(
    "/login",
    operation_id="login",
    summary="Log in with email and password (FR-U2)",
    dependencies=[Depends(auth_rate_limit)],
    responses={401: _error("Wrong email or password"), 429: _error("Too many requests")},
)
async def login(body: LoginRequest, service: Service) -> TokenPairOut:
    return TokenPairOut.of(await service.login(email=body.email, password=body.password))


@router.post(
    "/refresh",
    operation_id="refreshTokens",
    summary="Rotate the refresh token and issue a new pair",
    responses={401: _error("Unknown, expired or reused refresh token")},
)
async def refresh(body: RefreshRequest, service: Service) -> TokenPairOut:
    return TokenPairOut.of(await service.refresh(body.refresh_token))


@router.post(
    "/logout",
    operation_id="logout",
    summary="Revoke the refresh token family",
    status_code=204,
    response_class=Response,
    responses={401: _error("Invalid access or refresh token")},
)
async def logout(
    body: RefreshRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Service,
) -> Response:
    await service.logout(body.refresh_token, user.id)
    return Response(status_code=204)
