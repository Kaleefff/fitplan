"""Account deletion on PostgreSQL (B-05, FR-U5): nothing of the user is left.

The MongoDB buffer and the photos follow with DB-07. Skipped without PostgreSQL.
"""

import functools
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.seed import load
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

PASSWORD = "secret123"


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


@pytest.fixture
def api(migrated_db) -> Iterator[TestClient]:  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, injury_type, allergen, food_category"
                " RESTART IDENTITY CASCADE"
            )
        )
        load(db)
    engine = create_async_engine(database_url().set(database=TEST_DB))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repositories = Repositories(
        users=SqlUserRepository(factory),
        refresh_tokens=SqlRefreshTokenRepository(factory),
        profiles=SqlProfileReader(factory),
        workouts=SqlWorkoutUnitOfWork(factory),
        training_plans=SqlTrainingPlanUnitOfWork(factory),
        profile_data=SqlProfileUnitOfWork(factory),
        password_resets=SqlPasswordResetRepository(factory),
    )
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), repositories=repositories
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(engine.dispose)


def _owned_rows(user_id: int) -> dict[str, int]:
    """Rows that point at the user, directly or through a parent, per table."""
    counts = {}
    with _sync_engine().connect() as db:
        for table in Base.metadata.sorted_tables:
            if "user_id" in table.c:
                counts[table.name] = db.execute(
                    text(f"SELECT count(*) FROM {table.name} WHERE user_id = :u"), {"u": user_id}
                ).scalar_one()
    return counts


def test_deleting_the_account_leaves_nothing_of_the_user(api):
    pair = api.post(
        "/api/v1/auth/register",
        json={"email": "ann@example.com", "password": PASSWORD, "name": "A", "surname": "B"},
    ).json()
    keep = api.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": PASSWORD, "name": "B", "surname": "C"},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    api.put(
        "/api/v1/users/me/profile",
        json={
            "age": 30,
            "sex": "female",
            "current_weight": 60,
            "height": 165,
            "activity_level_pal": 1.375,
            "goal": "weight_loss",
            "experience_level": "beginner",
            "equipment": "home",
        },
        headers=headers,
    )
    api.post(
        "/api/v1/users/me/injuries",
        json={
            "injury_type_id": 1,
            "affected_muscle_group_id": 1,
            "severity": "mild",
            "start_date": date.today().isoformat(),
        },
        headers=headers,
    )
    api.put("/api/v1/users/me/allergies", json={"allergen_ids": [1, 2]}, headers=headers)
    api.post("/api/v1/auth/password/forgot", json={"email": "ann@example.com"})
    before = _owned_rows(1)
    assert sum(before.values()) >= 5  # tokens, profile, injury, allergens, reset token

    deleted = api.post("/api/v1/users/me/delete", json={"password": PASSWORD}, headers=headers)

    assert deleted.status_code == 204
    assert sum(_owned_rows(1).values()) == 0
    with _sync_engine().connect() as db:
        assert db.execute(text("SELECT count(*) FROM app_user WHERE id = 1")).scalar_one() == 0
    assert sum(_owned_rows(2).values()) > 0  # the other user is untouched
    login = {"email": "ann@example.com", "password": PASSWORD}
    assert api.post("/api/v1/auth/login", json=login).status_code == 401
    refresh = api.post("/api/v1/auth/refresh", json={"refresh_token": keep["refresh_token"]})
    assert refresh.status_code == 200
