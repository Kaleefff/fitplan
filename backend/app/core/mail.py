"""Outgoing mail over SMTP (aiosmtplib); Mailpit catches it in development (DB-05)."""

import logging
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.config import Settings

logger = logging.getLogger(__name__)


class MailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            await aiosmtplib.send(
                message, hostname=self._settings.smtp_host, port=self._settings.smtp_port
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            # runs after the response; never log the address (CLAUDE.md)
            logger.error("Sending mail failed: %s", type(exc).__name__)
