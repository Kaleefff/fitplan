from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_opaque_token,
    hash_password,
    new_opaque_token,
    password_length_ok,
    verify_password,
)
from tests.conftest import TEST_JWT_SECRET

ROUNDS = 4
NOW = datetime.now(UTC)
LIFETIME = timedelta(minutes=15)


# ---------------------------------------------------------------- passwords


@pytest.mark.parametrize(
    ("password", "ok"),
    [
        ("a" * 7, False),
        ("a" * 8, True),
        ("a" * 72, True),
        ("a" * 73, False),
        ("ł" * 36, True),  # 72 bytes in UTF-8
        ("ł" * 36 + "a", False),  # 73 bytes, only 37 characters
    ],
)
def test_password_length_is_counted_in_bytes(password, ok):
    assert password_length_ok(password) is ok


def test_hash_is_bcrypt_and_verifies():
    hashed = hash_password("correct horse", ROUNDS)
    assert hashed.startswith("$2b$04$")
    assert "correct horse" not in hashed
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong horse", hashed)


def test_hash_rejects_out_of_range_password():
    with pytest.raises(ValueError):
        hash_password("a" * 73, ROUNDS)


def test_verify_is_false_for_long_password_and_social_only_account():
    hashed = hash_password("a" * 72, ROUNDS)
    assert not verify_password("a" * 73, hashed)  # bcrypt alone would ignore byte 73
    assert not verify_password("anything", None)


# ---------------------------------------------------------------- access tokens


def test_access_token_round_trip():
    token = create_access_token(42, TEST_JWT_SECRET, LIFETIME, NOW)
    assert decode_access_token(token, TEST_JWT_SECRET) == 42


def test_expired_token_is_rejected():
    token = create_access_token(42, TEST_JWT_SECRET, LIFETIME, NOW - timedelta(minutes=16))
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, TEST_JWT_SECRET)


def test_tampered_payload_is_rejected():
    header, _, signature = create_access_token(42, TEST_JWT_SECRET, LIFETIME, NOW).split(".")
    forged = jwt.encode(
        {"sub": "1", "type": "access", "iat": NOW, "exp": NOW + LIFETIME}, "x" * 32
    ).split(".")[1]
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{forged}.{signature}", TEST_JWT_SECRET)


def test_token_signed_with_another_key_is_rejected():
    token = create_access_token(42, "another-secret-of-at-least-32-bytes", LIFETIME, NOW)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, TEST_JWT_SECRET)


def test_unsigned_token_is_rejected():
    token = jwt.encode(
        {"sub": "42", "type": "access", "iat": NOW, "exp": NOW + LIFETIME}, None, algorithm="none"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, TEST_JWT_SECRET)


@pytest.mark.parametrize(
    "payload",
    [
        {"sub": "42", "type": "refresh", "iat": NOW, "exp": NOW + LIFETIME},
        {"sub": "42", "iat": NOW, "exp": NOW + LIFETIME},
        {"sub": "not-a-number", "type": "access", "iat": NOW, "exp": NOW + LIFETIME},
        {"type": "access", "iat": NOW, "exp": NOW + LIFETIME},
    ],
)
def test_wrong_claims_are_rejected(payload):
    token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, TEST_JWT_SECRET)


def test_garbage_is_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.token", TEST_JWT_SECRET)


# ---------------------------------------------------------------- opaque tokens


def test_opaque_tokens_are_random_and_stored_as_sha256_hex():
    first, second = new_opaque_token(), new_opaque_token()
    assert first != second
    assert len(hash_opaque_token(first)) == 64
    assert hash_opaque_token(first) == hash_opaque_token(first)
    assert hash_opaque_token(first) != hash_opaque_token(second)
