"""Passwords, access tokens and opaque tokens (B-02, api-rules.md "Auth and account")."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
import jwt

PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 72  # bcrypt ignores everything after 72 bytes, so longer input is rejected

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"


class InvalidTokenError(Exception):
    """The access token is missing, malformed, tampered with or expired."""


def password_length_ok(password: str) -> bool:
    return PASSWORD_MIN_BYTES <= len(password.encode("utf-8")) <= PASSWORD_MAX_BYTES


def hash_password(password: str, rounds: int) -> str:
    if not password_length_ok(password):
        raise ValueError(f"password must be {PASSWORD_MIN_BYTES}-{PASSWORD_MAX_BYTES} bytes")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """False for a wrong password, an over-long one, or an account without a password."""
    if password_hash is None or len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


def create_access_token(user_id: int, key: str, lifetime: timedelta, now: datetime) -> str:
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, key: str) -> int:
    """Returns the user id; `exp` is checked against the real clock."""
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "type", "iat", "exp"]},
        )
        if payload["type"] != ACCESS_TOKEN_TYPE:
            raise InvalidTokenError("not an access token")
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(type(exc).__name__) from exc


def new_opaque_token() -> str:
    """Refresh and password reset tokens: 256 random bits, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """SHA-256 hex (64 chars, `token_hash CHAR(64)`); only the hash is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
