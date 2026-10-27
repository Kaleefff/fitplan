"""Register, login, refresh, logout (B-03, FR-U1, FR-U2; api-rules.md "Auth and account")."""

from functools import lru_cache
from typing import Protocol

from anyio import to_thread

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password, verify_password
from app.db.repositories.users import EmailTakenError, UserRecord
from app.services.tokens import InvalidRefreshTokenError, TokenPair, TokenService

INVALID_CREDENTIALS = "Invalid email or password"


class UserRepository(Protocol):
    async def add(
        self, *, email: str, password_hash: str | None, name: str, surname: str
    ) -> UserRecord: ...

    async def get_by_email(self, email: str) -> UserRecord | None: ...

    async def get_by_id(self, user_id: int) -> UserRecord | None: ...


@lru_cache
def _dummy_hash(rounds: int) -> str:
    # an unknown email still costs one bcrypt check, so timing does not reveal accounts
    return hash_password("timing-equaliser-1", rounds)


class AuthService:
    def __init__(self, settings: Settings, users: UserRepository, tokens: TokenService) -> None:
        self._settings = settings
        self._users = users
        self._tokens = tokens

    async def register(self, *, email: str, password: str, name: str, surname: str) -> TokenPair:
        # bcrypt is slow on purpose; keep it off the event loop
        password_hash = await to_thread.run_sync(
            hash_password, password, self._settings.bcrypt_rounds
        )
        try:
            user = await self._users.add(
                email=email, password_hash=password_hash, name=name, surname=surname
            )
        except EmailTakenError:
            raise AppError(
                409,
                ErrorCode.CONFLICT,
                "Email is already registered",
                [
                    {
                        "field": "body.email",
                        "code": "taken",
                        "message": "Email is already registered",
                    }
                ],
            ) from None
        return await self._tokens.issue_pair(user.id)

    async def login(self, *, email: str, password: str) -> TokenPair:
        """Unknown email, wrong password and a social-only account answer the same."""
        user = await self._users.get_by_email(email)
        if user is None:
            await to_thread.run_sync(
                verify_password, password, _dummy_hash(self._settings.bcrypt_rounds)
            )
            raise AppError(401, ErrorCode.INVALID_CREDENTIALS, INVALID_CREDENTIALS)
        if not await to_thread.run_sync(verify_password, password, user.password_hash):
            raise AppError(401, ErrorCode.INVALID_CREDENTIALS, INVALID_CREDENTIALS)
        return await self._tokens.issue_pair(user.id)

    async def refresh(self, refresh_token: str) -> TokenPair:
        try:
            return await self._tokens.rotate(refresh_token)
        except InvalidRefreshTokenError:
            raise AppError(401, ErrorCode.UNAUTHORIZED, "Invalid refresh token") from None

    async def logout(self, refresh_token: str, user_id: int) -> None:
        try:
            await self._tokens.logout(refresh_token, user_id)
        except InvalidRefreshTokenError:
            raise AppError(401, ErrorCode.UNAUTHORIZED, "Invalid refresh token") from None
