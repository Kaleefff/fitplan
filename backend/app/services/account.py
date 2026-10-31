"""Account settings and deletion (B-05; FR-U4, FR-U5; api-rules.md "Auth and account").

Changing the email or the password needs the current password (wrong: 401
invalid_credentials); a social-only account has none (422 no_password). A password
change ends every session; an email change keeps them, and the same email is a no-op.
"""

import logging

from anyio import to_thread

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password, verify_password
from app.db.repositories.users import EmailTakenError, UserRecord
from app.services.auth import UserRepository
from app.services.tokens import TokenService

logger = logging.getLogger(__name__)


def _no_password(field: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed",
        [{"field": field, "code": "no_password", "message": "The account has no password"}],
    )


class AccountService:
    def __init__(self, settings: Settings, users: UserRepository, tokens: TokenService) -> None:
        self._settings = settings
        self._users = users
        self._tokens = tokens

    async def get(self, user_id: int) -> UserRecord:
        user = await self._users.get_by_id(user_id)
        if user is None:  # deleted while the access token is still valid
            raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
        return user

    async def update(self, user_id: int, fields: dict[str, str]) -> UserRecord:
        user = await self._users.update(user_id, **fields)
        if user is None:
            raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
        return user

    async def _check_password(self, user: UserRecord, password: str | None, field: str) -> None:
        if user.password_hash is None:
            raise _no_password(field)
        if password is None or not await to_thread.run_sync(
            verify_password, password, user.password_hash
        ):
            raise AppError(401, ErrorCode.INVALID_CREDENTIALS, "Wrong password")

    async def change_email(self, user_id: int, new_email: str, current_password: str) -> UserRecord:
        user = await self.get(user_id)
        await self._check_password(user, current_password, "body.current_password")
        if new_email == user.email:
            return user
        try:
            await self._users.set_email(user_id, new_email)
        except EmailTakenError:
            raise AppError(
                409,
                ErrorCode.CONFLICT,
                "Email is already registered",
                [
                    {
                        "field": "body.new_email",
                        "code": "taken",
                        "message": "Email is already registered",
                    }
                ],
            ) from None
        return await self.get(user_id)

    async def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        user = await self.get(user_id)
        await self._check_password(user, current_password, "body.current_password")
        password_hash = await to_thread.run_sync(
            hash_password, new_password, self._settings.bcrypt_rounds
        )
        await self._users.set_password(user_id, password_hash)
        await self._tokens.revoke_all(user_id)

    async def delete(self, user_id: int, password: str | None) -> None:
        """PostgreSQL first: app_user cascades to every owned row (FR-U5). The MongoDB
        buffer and the photo files follow with DB-07; until then there is nothing there
        for the API to remove (no recognition endpoint stores anything yet)."""
        user = await self.get(user_id)
        if user.password_hash is not None:  # a social-only account needs no password
            await self._check_password(user, password, "body.password")
        await self._users.delete(user_id)
        logger.info("Account %s deleted", user_id)
