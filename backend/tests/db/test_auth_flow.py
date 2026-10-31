"""The app against a real PostgreSQL: auth (B-03) and nutrition targets (B-10) end to end.

Uses the throwaway database of test_repositories; skipped without PostgreSQL.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

PASSWORD = "secret123"


@pytest.fixture
def api(migrated_db) -> Iterator[TestClient]:  # noqa: F811
    with create_engine(database_url().set(database=TEST_DB)).begin() as connection:
        connection.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
    engine = create_async_engine(database_url().set(database=TEST_DB))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repositories = Repositories(
        users=SqlUserRepository(sessions),
        refresh_tokens=SqlRefreshTokenRepository(sessions),
        profiles=SqlProfileReader(sessions),
        workouts=SqlWorkoutUnitOfWork(sessions),
        training_plans=SqlTrainingPlanUnitOfWork(sessions),
        profile_data=SqlProfileUnitOfWork(sessions),
    )
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), repositories=repositories
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        # connections belong to the client's event loop
        client.portal.call(engine.dispose)


def _post(api, path, body, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return api.post(f"/api/v1/auth/{path}", json=body, headers=headers)


def _refresh(api, pair: dict):
    return _post(api, "refresh", {"refresh_token": pair["refresh_token"]})


def test_account_lifecycle(api):
    account = {"email": "ann@example.com", "password": PASSWORD, "name": "Ann", "surname": "N"}

    registered = _post(api, "register", account)
    assert registered.status_code == 201
    assert _post(api, "register", account).status_code == 409

    wrong = _post(api, "login", {"email": "ann@example.com", "password": "nope1234"})
    assert wrong.json()["code"] == "invalid_credentials"
    login = _post(api, "login", {"email": "ann@example.com", "password": PASSWORD})
    assert login.status_code == 200

    rotated = _refresh(api, login.json())
    assert rotated.status_code == 200
    # reusing the rotated token revokes the login's family, not the registration's
    assert _refresh(api, login.json()).status_code == 401
    assert _refresh(api, rotated.json()).status_code == 401

    pair = registered.json()
    logout = _post(api, "logout", {"refresh_token": pair["refresh_token"]}, pair["access_token"])
    assert logout.status_code == 204
    assert _refresh(api, pair).status_code == 401


def test_nutrition_targets_from_the_stored_profile(api):
    pair = _post(
        api,
        "register",
        {"email": "ann@example.com", "password": PASSWORD, "name": "Ann", "surname": "N"},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    assert api.get("/api/v1/nutrition/targets", headers=headers).status_code == 404

    with create_engine(database_url().set(database=TEST_DB)).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_profile (user_id, age, sex, current_weight, height,"
                " activity_level_pal, goal, experience_level, equipment, tdee)"
                " VALUES (1, 25, 'male', 80, 180, 1.55, 'muscle_gain', 'beginner', 'gym', 2798)"
            )
        )

    response = api.get("/api/v1/nutrition/targets", headers=headers)

    # first vector of algorithms.md 2
    assert response.json() == {
        "goal": "muscle_gain",
        "bmr": 1805.0,
        "tdee": 2798,
        "target_kcal": 3078,
        "protein_g": 144.0,
        "fat_g": 85.5,
        "carbs_g": 433.1,
    }
