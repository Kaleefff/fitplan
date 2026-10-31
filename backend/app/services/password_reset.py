"""Password reset by mail (B-04, FR-U3; api-rules.md "Auth and account").

Same answer whether the email exists or not; the mail goes out after the response,
so timing does not tell either. The token is stored hashed, used once, expires after
an hour; a reset ends every session of the user.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

from anyio import to_thread

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.mail import MailSender
from app.core.security import hash_opaque_token, hash_password, new_opaque_token
from app.services.auth import UserRepository


class PasswordResetRepository(Protocol):
    async def add(self, user_id: int, token_hash: str, expires_at: datetime) -> None: ...

    async def reset(self, token_hash: str, now: datetime, password_hash: str) -> int | None: ...


@dataclass(frozen=True)
class ResetMail:
    to: str
    subject: str
    body: str


class PasswordResetService:
    def __init__(
        self,
        settings: Settings,
        users: UserRepository,
        resets: PasswordResetRepository,
        mail: MailSender,
    ) -> None:
        self._settings = settings
        self._users = users
        self._resets = resets
        self._mail = mail

    async def request(self, email: str, now: datetime) -> ResetMail | None:
        """Stores a token and returns the mail to send, or None for an unknown email or a
        social-only account. The caller answers 202 either way."""
        user = await self._users.get_by_email(email)
        if user is None or user.password_hash is None:
            return None
        token = new_opaque_token()
        minutes = self._settings.password_reset_minutes
        await self._resets.add(user.id, hash_opaque_token(token), now + timedelta(minutes=minutes))
        link = f"{self._settings.password_reset_url}?{urlencode({'token': token})}"
        return ResetMail(
            to=user.email,
            subject="Reset your FitPlan Pro password",
            body=(
                f"Hello {user.name},\n\n"
                f"open this link in the FitPlan Pro app to choose a new password:\n{link}\n\n"
                f"The link works once and expires in {minutes} minutes. If you did not ask "
                "for it, ignore this mail; your password stays the same.\n"
            ),
        )

    async def send(self, mail: ResetMail) -> None:
        await self._mail.send(mail.to, mail.subject, mail.body)

    async def reset(self, token: str, new_password: str, now: datetime) -> None:
        password_hash = await to_thread.run_sync(
            hash_password, new_password, self._settings.bcrypt_rounds
        )
        if await self._resets.reset(hash_opaque_token(token), now, password_hash) is None:
            raise AppError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                [
                    {
                        "field": "body.token",
                        "code": "invalid_token",
                        "message": "The link is invalid, used or expired",
                    }
                ],
            )
