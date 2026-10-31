"""Body measurements on PostgreSQL (B-17): one per day, client_uuid, profile weight.

Skipped without PostgreSQL.
"""

import functools
import uuid
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.body_metrics import SqlBodyMetricsUnitOfWork
from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.schedule import SqlScheduleUnitOfWork
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

TODAY = date.today()
PROFILE = {
    "age": 25,
    "sex": "male",
    "current_weight": 80,
    "height": 180,
    "activity_level_pal": 1.55,
    "goal": "weight_loss",
    "experience_level": "beginner",
    "equipment": "gym",
}


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
        db.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
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
        body_metrics=SqlBodyMetricsUnitOfWork(factory),
        schedule=SqlScheduleUnitOfWork(factory),
    )
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), repositories=repositories
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(engine.dispose)


def _login(api, email="ann@example.com", profile=True) -> dict[str, str]:
    pair = api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "name": "A", "surname": "B"},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    if profile:
        api.put("/api/v1/users/me/profile", json=PROFILE, headers=headers)
    return headers


def _save(api, headers, day=TODAY, weight=75, **extra):
    return api.post(
        "/api/v1/body-metrics",
        json={"measured_on": day.isoformat(), "weight": weight, **extra},
        headers=headers,
    )


def _profile(api, headers) -> dict:
    return api.get("/api/v1/users/me/profile", headers=headers).json()


def _live_rows() -> int:
    with _sync_engine().connect() as db:
        return db.execute(
            text("SELECT count(*) FROM body_metrics WHERE deleted_at IS NULL")
        ).scalar_one()


def test_the_newest_measurement_updates_the_profile_and_tdee(api):
    headers = _login(api)
    before = _profile(api, headers)

    saved = _save(api, headers, weight=75, waist=82.5)

    assert saved.status_code == 201
    body = saved.json()
    assert (body["weight"], body["waist"], body["chest"]) == (75.0, 82.5, None)
    after = _profile(api, headers)
    assert after["current_weight"] == 75.0
    assert after["tdee"] < before["tdee"]
    assert api.get("/api/v1/nutrition/targets", headers=headers).json()["tdee"] == after["tdee"]


def test_a_backdated_measurement_leaves_the_profile(api):
    headers = _login(api)
    _save(api, headers, weight=75)
    _save(api, headers, day=TODAY - timedelta(10), weight=82)

    assert _profile(api, headers)["current_weight"] == 75.0


def test_saving_the_same_day_again_replaces_it(api):
    headers = _login(api)
    first = _save(api, headers, weight=75, chest=100).json()
    second = _save(api, headers, weight=74).json()

    assert second["id"] == first["id"]
    assert (second["weight"], second["chest"]) == (74.0, None)  # fields not sent become null
    assert _live_rows() == 1


def test_a_repeated_client_uuid_applies_nothing_twice(api):
    headers = _login(api)
    client_uuid = str(uuid.uuid4())
    first = _save(api, headers, weight=75, client_uuid=client_uuid)
    api.put("/api/v1/users/me/profile", json={**PROFILE, "current_weight": 90}, headers=headers)

    again = _save(api, headers, weight=75, client_uuid=client_uuid)

    assert again.status_code == 201
    assert again.json() == first.json()
    assert _profile(api, headers)["current_weight"] == 90.0  # the later profile edit wins


def test_client_uuid_moves_to_a_free_day_but_not_to_a_taken_one(api):
    headers = _login(api)
    client_uuid = str(uuid.uuid4())
    yesterday = TODAY - timedelta(1)
    saved = _save(api, headers, day=yesterday, weight=76, client_uuid=client_uuid).json()

    moved = _save(api, headers, day=TODAY - timedelta(2), weight=76, client_uuid=client_uuid)
    assert moved.status_code == 201
    assert (moved.json()["id"], moved.json()["measured_on"]) == (
        saved["id"],
        (TODAY - timedelta(2)).isoformat(),
    )

    _save(api, headers, day=TODAY, weight=75)
    taken = _save(api, headers, day=TODAY, weight=76, client_uuid=client_uuid)
    assert taken.status_code == 409
    assert taken.json()["details"][0]["field"] == "body.measured_on"


def test_deleting_the_newest_restores_the_previous_weight(api):
    headers = _login(api)
    _save(api, headers, day=TODAY - timedelta(7), weight=78)
    newest = _save(api, headers, weight=75).json()
    assert _profile(api, headers)["current_weight"] == 75.0

    assert api.delete(f"/api/v1/body-metrics/{newest['id']}", headers=headers).status_code == 204

    assert _profile(api, headers)["current_weight"] == 78.0
    assert api.delete(f"/api/v1/body-metrics/{newest['id']}", headers=headers).status_code == 404
    reused = _save(api, headers, weight=75, client_uuid=newest["client_uuid"])
    assert reused.status_code == 409  # the client_uuid of a deleted row


def test_another_users_rows_and_uuids(api):
    ann = _login(api)
    bob = _login(api, "bob@example.com")
    anns = _save(api, ann, weight=75).json()

    assert api.delete(f"/api/v1/body-metrics/{anns['id']}", headers=bob).status_code == 404
    assert _save(api, bob, weight=90, client_uuid=anns["client_uuid"]).status_code == 409
    assert api.get("/api/v1/body-metrics", headers=bob).json() == []


def test_without_a_profile_the_measurement_is_still_stored(api):
    headers = _login(api, profile=False)
    assert _save(api, headers).status_code == 201
    assert api.get("/api/v1/users/me/profile", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"weight": 29},
        {"weight": 301},
        {"fat_percentage": 100},
        {"chest": 0},
        {"day": TODAY + timedelta(2)},
    ],
)
def test_invalid_measurements_are_422(api, change):
    headers = _login(api)
    day = change.pop("day", TODAY)
    response = _save(api, headers, day=day, **{"weight": 75, **change})
    assert response.status_code == 422
    assert _live_rows() == 0


def test_history_is_newest_first_and_filtered(api):
    headers = _login(api)
    for days_ago in (3, 0, 10):
        _save(api, headers, day=TODAY - timedelta(days_ago), weight=75 + days_ago)

    history = api.get("/api/v1/body-metrics", headers=headers).json()
    ranged = api.get(
        "/api/v1/body-metrics",
        params={"from": (TODAY - timedelta(5)).isoformat()},
        headers=headers,
    ).json()

    assert [m["weight"] for m in history] == [75.0, 78.0, 85.0]
    assert [m["weight"] for m in ranged] == [75.0, 78.0]
