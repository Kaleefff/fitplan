"""Reminders, moving a session, notifications on PostgreSQL (B-14). Skipped without it."""

import functools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

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
from tests.db.test_training_plans import _load_seed


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
                "TRUNCATE app_user, muscle_group, exercise, exercise_muscle_group, injury_type,"
                " allergen, food_category RESTART IDENTITY CASCADE"
            )
        )
    _load_seed()
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


def _login(api, email="ann@example.com") -> dict[str, str]:
    pair = api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "name": "A", "surname": "B"},
    ).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}


REMINDERS = [
    {
        "message_type": "training_reminder",
        "day_of_week": 3,
        "time_of_day": "18:00:00",
        "message": "Full Body today",
    },
    {
        "message_type": "meal_reminder",
        "day_of_week": None,
        "time_of_day": "08:00:00",
        "message": "Breakfast",
        "is_enabled": False,
    },
]


def test_reminders_round_trip_and_are_replaced_as_a_whole(api):
    headers = _login(api)
    assert api.get("/api/v1/reminders", headers=headers).json() == []

    saved = api.put("/api/v1/reminders", json=REMINDERS, headers=headers)

    assert saved.status_code == 200
    body = saved.json()
    # every day first, then by weekday; the wall-clock time is kept as sent
    assert [(r["day_of_week"], r["time_of_day"], r["is_enabled"]) for r in body] == [
        (None, "08:00:00", False),
        (3, "18:00:00", True),
    ]
    assert api.get("/api/v1/reminders", headers=headers).json() == body

    replaced = api.put("/api/v1/reminders", json=REMINDERS[:1], headers=headers).json()
    assert len(replaced) == 1
    assert api.put("/api/v1/reminders", json=[], headers=headers).json() == []
    other = _login(api, "bob@example.com")
    assert api.get("/api/v1/reminders", headers=other).json() == []


def test_reminder_validation(api):
    headers = _login(api)
    too_many = api.put("/api/v1/reminders", json=REMINDERS[:1] * 51, headers=headers)
    bad_day = api.put(
        "/api/v1/reminders", json=[{**REMINDERS[0], "day_of_week": 8}], headers=headers
    )
    bad_type = api.put(
        "/api/v1/reminders", json=[{**REMINDERS[0], "message_type": "achievement"}], headers=headers
    )
    assert too_many.status_code == bad_day.status_code == bad_type.status_code == 422


def _plan(api, headers, accept=False):
    plan = api.post(
        "/api/v1/training-plans/generate",
        json={
            "goal": "strength",
            "num_training_days": 3,
            "experience_level": "beginner",
            "equipment": "gym",
        },
        headers=headers,
    ).json()
    if accept:
        api.post(f"/api/v1/training-plans/{plan['id']}/accept", headers=headers)
    return plan


def test_moving_a_session_round_trips_and_a_taken_weekday_is_409(api):
    headers = _login(api)
    plan = _plan(api, headers)  # Mon, Wed, Fri
    monday = plan["sessions"][0]
    url = f"/api/v1/training-sessions/{monday['id']}"

    moved = api.patch(url, json={"day_of_week": 2}, headers=headers)
    assert moved.status_code == 200
    assert moved.json()["day_of_week"] == 2
    assert moved.json()["exercises"] == monday["exercises"]
    again = api.get(f"/api/v1/training-plans/{plan['id']}", headers=headers).json()
    assert [s["day_of_week"] for s in again["sessions"]] == [2, 3, 5]

    clash = api.patch(url, json={"day_of_week": 3}, headers=headers)
    assert clash.status_code == 409
    assert clash.json()["details"][0]["field"] == "body.day_of_week"
    assert api.patch(url, json={"day_of_week": 2}, headers=headers).status_code == 200  # same day


def test_moving_a_session_of_another_user_or_an_archived_plan(api):
    headers = _login(api)
    first = _plan(api, headers, accept=True)
    _plan(api, headers, accept=True)  # archives the first
    archived = first["sessions"][0]["id"]
    assert (
        api.patch(
            f"/api/v1/training-sessions/{archived}", json={"day_of_week": 7}, headers=headers
        ).status_code
        == 409
    )

    bob = _login(api, "bob@example.com")
    assert (
        api.patch(
            f"/api/v1/training-sessions/{archived}", json={"day_of_week": 7}, headers=bob
        ).status_code
        == 404
    )


def test_notifications_due_newest_first_paginated(api):
    headers = _login(api)
    now = datetime.now(UTC)
    with _sync_engine().begin() as db:
        for minutes, message in ((-60, "older"), (-1, "newer"), (60, "future")):
            db.execute(
                text(
                    "INSERT INTO notification (user_id, message_type, scheduled_at, message)"
                    " VALUES (1, 'achievement', :at, :m)"
                ),
                {"at": now + timedelta(minutes=minutes), "m": message},
            )

    page = api.get("/api/v1/notifications", params={"limit": 1}, headers=headers).json()
    rest = api.get("/api/v1/notifications", params={"offset": 1}, headers=headers).json()

    assert (page["total"], [n["message"] for n in page["items"]]) == (2, ["newer"])
    assert [n["message"] for n in rest["items"]] == ["older"]
    assert (
        api.get("/api/v1/notifications", headers=_login(api, "bob@example.com")).json()["total"]
        == 0
    )
