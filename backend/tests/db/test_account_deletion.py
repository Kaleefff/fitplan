"""Account deletion (B-05, FR-U5): nothing of the user is left in PostgreSQL, in the
MongoDB buffer or in `PHOTO_DIR`. Skipped without PostgreSQL or MongoDB.
"""

import functools
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient, MongoClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.repositories.analytics import SqlAnalyticsUnitOfWork
from app.db.repositories.body_metrics import SqlBodyMetricsUnitOfWork
from app.db.repositories.diet_plans import SqlDietPlanUnitOfWork
from app.db.repositories.library import SqlLibraryRepository
from app.db.repositories.meal_recognitions import COLLECTION, MongoMealRecognitionRepository
from app.db.repositories.nutrition_logs import SqlNutritionLogUnitOfWork
from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.schedule import SqlScheduleUnitOfWork
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.seed import load
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.conftest import MONGO_TEST_DB
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
def buffer(mongo_reachable) -> Iterator:
    """The buffer collection, read and seeded synchronously from the test."""
    client = MongoClient(**get_settings().mongo_client_kwargs(), serverSelectionTimeoutMS=1000)
    collection = client[MONGO_TEST_DB][COLLECTION]
    collection.drop()
    yield collection
    collection.drop()
    client.close()


@pytest.fixture
def api(migrated_db, buffer, tmp_path) -> Iterator[TestClient]:  # noqa: F811
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
        body_metrics=SqlBodyMetricsUnitOfWork(factory),
        schedule=SqlScheduleUnitOfWork(factory),
        diet_plans=SqlDietPlanUnitOfWork(factory),
        analytics=SqlAnalyticsUnitOfWork(factory),
        library=SqlLibraryRepository(factory),
        nutrition_logs=SqlNutritionLogUnitOfWork(factory),
    )
    # used only on the TestClient's event loop
    mongo = AsyncMongoClient(**get_settings().mongo_client_kwargs(), serverSelectionTimeoutMS=1000)
    app = create_app(
        settings=make_settings(photo_dir=tmp_path),
        health_checker=FakeHealthChecker(),
        repositories=repositories,
        recognitions=MongoMealRecognitionRepository(mongo[MONGO_TEST_DB]),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(mongo.close)
        client.portal.call(engine.dispose)


def _buffered(buffer, tmp_path, user_id: int, name: str) -> None:
    """A pending recognition document and its photo (purge_user ignores expiresAt;
    expired documents are covered in test_meal_recognitions)."""
    now = datetime.now(UTC)
    photo_url = f"meals/{user_id}/{name}"
    path = tmp_path / photo_url
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    buffer.insert_one(
        {
            "userId": user_id,
            "status": "pending",
            "mealType": "lunch",
            "photoUrl": photo_url,
            "model": {"name": "food101-vit", "version": "1.0"},
            "overallConfidence": 0.5,
            "recognisedItems": [],
            "createdAt": now,
            "expiresAt": now + timedelta(hours=6),
        }
    )


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


def test_deleting_the_account_leaves_nothing_of_the_user(api, buffer, tmp_path):
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
    _buffered(buffer, tmp_path, 1, "a.jpg")
    _buffered(buffer, tmp_path, 1, "b.jpg")
    _buffered(buffer, tmp_path, 2, "c.jpg")
    before = _owned_rows(1)
    assert sum(before.values()) >= 5  # tokens, profile, injury, allergens, reset token

    deleted = api.post("/api/v1/users/me/delete", json={"password": PASSWORD}, headers=headers)

    assert deleted.status_code == 204
    assert sum(_owned_rows(1).values()) == 0
    assert buffer.count_documents({"userId": 1}) == 0
    assert not (tmp_path / "meals" / "1").exists()
    assert buffer.count_documents({"userId": 2}) == 1  # the other user's buffer and photo
    assert (tmp_path / "meals" / "2" / "c.jpg").exists()
    with _sync_engine().connect() as db:
        assert db.execute(text("SELECT count(*) FROM app_user WHERE id = 1")).scalar_one() == 0
    assert sum(_owned_rows(2).values()) > 0  # the other user is untouched
    login = {"email": "ann@example.com", "password": PASSWORD}
    assert api.post("/api/v1/auth/login", json=login).status_code == 401
    refresh = api.post("/api/v1/auth/refresh", json={"refresh_token": keep["refresh_token"]})
    assert refresh.status_code == 200
