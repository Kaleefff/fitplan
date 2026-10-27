"""Account and profile repositories on a real PostgreSQL (questions.md, B-03).

A throwaway database (fitplan_repo_test) is migrated once per module and emptied
between tests; skipped when PostgreSQL is not reachable, like test_migrations.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.users import EmailTakenError, SqlUserRepository
from app.db.session import database_url
from app.domain.constants import Goal, Sex
from app.services.tokens import InvalidRefreshTokenError, TokenService
from tests.conftest import make_settings
from tests.db.test_migrations import run_alembic

TEST_DB = "fitplan_repo_test"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def migrated_db() -> Iterator[None]:
    admin = create_engine(database_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL is not reachable: run docker compose up -d")

    def recreate(create: bool) -> None:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            if create:
                connection.execute(text(f"CREATE DATABASE {TEST_DB}"))

    recreate(create=True)
    engine: Engine = create_engine(database_url().set(database=TEST_DB))
    run_alembic(engine, "upgrade", "head")
    engine.dispose()
    yield
    recreate(create=False)
    admin.dispose()


@pytest.fixture
async def sessions(migrated_db) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url().set(database=TEST_DB))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _user(sessions, email: str = "ann@example.com") -> int:
    user = await SqlUserRepository(sessions).add(
        email=email, password_hash="$2b$04$hash", name="Ann", surname="Nowak"
    )
    return user.id


# ---------------------------------------------------------------- users


async def test_user_round_trip_with_server_defaults(sessions):
    users = SqlUserRepository(sessions)
    created = await users.add(email="ann@example.com", password_hash="h", name="Ann", surname="N")

    assert created.timezone == "Europe/Warsaw"
    assert created.registration_date is not None
    assert await users.get_by_email("ann@example.com") == created
    assert await users.get_by_id(created.id) == created
    assert await users.get_by_email("bob@example.com") is None


async def test_duplicate_email_is_email_taken(sessions):
    users = SqlUserRepository(sessions)
    await users.add(email="ann@example.com", password_hash="h", name="Ann", surname="N")
    with pytest.raises(EmailTakenError):
        await users.add(email="ann@example.com", password_hash="h", name="Ann", surname="N")


# ---------------------------------------------------------------- refresh tokens


async def test_refresh_token_round_trip(sessions):
    repo = SqlRefreshTokenRepository(sessions)
    user_id = await _user(sessions)
    family = uuid.uuid4()
    row = await repo.add(
        user_id=user_id,
        family_id=family,
        token_hash="a" * 64,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )

    assert await repo.get_by_hash("a" * 64) == row
    assert row.family_id == family
    assert row.revoked_at is None
    assert await repo.get_by_hash("b" * 64) is None


async def test_concurrent_replace_has_exactly_one_winner(sessions):
    repo = SqlRefreshTokenRepository(sessions)
    user_id = await _user(sessions)
    family = uuid.uuid4()
    rows = [
        await repo.add(
            user_id=user_id,
            family_id=family,
            token_hash=char * 64,
            issued_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
        for char in "abc"
    ]
    old, first, second = rows

    results = await asyncio.gather(
        repo.replace(old.id, replaced_by_id=first.id, revoked_at=NOW),
        repo.replace(old.id, replaced_by_id=second.id, revoked_at=NOW),
    )

    assert sorted(results) == [False, True]


async def test_revoke_family_and_user(sessions):
    repo = SqlRefreshTokenRepository(sessions)
    ann, bob = await _user(sessions), await _user(sessions, "bob@example.com")
    family = uuid.uuid4()
    expiry = NOW + timedelta(days=30)
    in_family = await repo.add(
        user_id=ann, family_id=family, token_hash="a" * 64, issued_at=NOW, expires_at=expiry
    )
    other_family = await repo.add(
        user_id=ann, family_id=uuid.uuid4(), token_hash="b" * 64, issued_at=NOW, expires_at=expiry
    )
    bobs = await repo.add(
        user_id=bob, family_id=uuid.uuid4(), token_hash="c" * 64, issued_at=NOW, expires_at=expiry
    )

    await repo.revoke_family(family, NOW)
    assert (await repo.get_by_hash(in_family.token_hash)).revoked_at == NOW
    assert (await repo.get_by_hash(other_family.token_hash)).revoked_at is None

    await repo.revoke_user(ann, NOW)
    assert (await repo.get_by_hash(other_family.token_hash)).revoked_at == NOW
    assert (await repo.get_by_hash(bobs.token_hash)).revoked_at is None


async def test_token_service_reuse_detection_survives_on_the_real_store(sessions):
    """The family revocation is committed although rotate then raises."""
    service = TokenService(make_settings(), SqlRefreshTokenRepository(sessions))
    user_id = await _user(sessions)
    first = await service.issue_pair(user_id)
    second = await service.rotate(first.refresh_token)

    with pytest.raises(InvalidRefreshTokenError):
        await service.rotate(first.refresh_token)  # reuse
    with pytest.raises(InvalidRefreshTokenError):
        await service.rotate(second.refresh_token)  # the whole family is gone


# ---------------------------------------------------------------- profiles


async def test_profile_reader_maps_the_row(sessions):
    user_id = await _user(sessions)
    async with sessions.begin() as session:
        await session.execute(
            text(
                "INSERT INTO user_profile (user_id, age, sex, current_weight, height,"
                " activity_level_pal, goal, experience_level, equipment, tdee)"
                " VALUES (:id, 25, 'male', 80, 180, 1.55, 'muscle_gain', 'beginner', 'gym', 2798)"
            ),
            {"id": user_id},
        )

    profile = await SqlProfileReader(sessions).get_profile(user_id)

    assert profile is not None
    assert (profile.sex, profile.goal, profile.age, profile.height) == (
        Sex.MALE,
        Goal.MUSCLE_GAIN,
        25,
        180,
    )
    assert (profile.current_weight, profile.activity_level_pal) == (Decimal("80"), Decimal("1.55"))
    assert await SqlProfileReader(sessions).get_profile(user_id + 1) is None
