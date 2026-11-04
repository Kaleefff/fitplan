"""MongoDB buffer repository on a real MongoDB (DB-07, FR-N4, FR-U5).

`buffer_db` (tests/db/conftest.py) is a throwaway database, skipped without MongoDB.
Every `expiresAt` written here lies in the real future, so the TTL monitor never
removes a document mid-test; expiry is simulated by advancing the injected clock.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.core.config import get_settings
from app.db.enums import MealType
from app.db.repositories.meal_recognitions import (
    COLLECTION,
    INDEXES,
    RECOGNITION_TTL,
    Candidate,
    MealRecognition,
    MongoMealRecognitionRepository,
    Nutrition,
    RecognisedItem,
    RecognitionModel,
)
from app.main import create_app
from tests.conftest import make_settings
from tests.db.conftest import MONGO_TEST_DB

INIT_SCRIPT = (
    Path(__file__).resolve().parents[3] / "database" / "mongo-init" / "01_meal_recognitions.js"
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime.now(UTC))


def item(name: str = "pizza", grams: float = 250.0, corrected: bool = False) -> RecognisedItem:
    return RecognisedItem(
        name=name,
        food_item_id=7,
        candidates=(Candidate("pizza", 0.82, 7), Candidate("lasagna", 0.11, None)),
        confidence=0.82,
        low_confidence=False,
        grams=grams,
        nutrition=Nutrition(kcal=665.0, protein=28.5, fat=24.25, carbs=82.0),
        allergy_warning=True,
        corrected=corrected,
    )


async def create(repo: MongoMealRecognitionRepository, user_id: int = 1) -> MealRecognition:
    return await repo.create(
        user_id=user_id,
        meal_type=MealType.LUNCH,
        photo_url=f"meals/{user_id}/{ObjectId()}.jpg",
        model=RecognitionModel(name="food101-vit", version="1.0"),
        overall_confidence=0.82,
        items=[item()],
    )


# ---------------------------------------------------------------- expiry (Done criterion)


async def test_expired_document_not_yet_removed_is_never_returned(buffer_db, clock):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    created = await create(repo)
    clock.now = created.expires_at + timedelta(seconds=1)  # the real expiresAt is still ahead

    assert await repo.get(1, created.id) is None
    assert await repo.update_items(1, created.id, [item("salad")]) is None
    assert await repo.delete(1, created.id) is False

    raw = await buffer_db[COLLECTION].find_one({"_id": ObjectId(created.id)})
    assert raw is not None  # still stored: the repository, not the TTL monitor, hid it
    assert raw["recognisedItems"][0]["name"] == "pizza"  # and the update did not apply


async def test_document_is_returned_until_its_expiry(buffer_db, clock):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    created = await create(repo)
    clock.now = created.expires_at - timedelta(milliseconds=1)

    assert await repo.get(1, created.id) == created
    clock.now = created.expires_at  # expiresAt > now is strict
    assert await repo.get(1, created.id) is None


# ---------------------------------------------------------------- round trip


async def test_round_trip_keeps_every_field_and_type(buffer_db, clock):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    created = await create(repo)

    assert len(created.id) == 24 and ObjectId.is_valid(created.id)
    assert created.status == "pending"
    assert created.meal_type is MealType.LUNCH
    assert created.created_at.utcoffset() == timedelta(0)
    assert created.expires_at - created.created_at == RECOGNITION_TTL
    assert abs(created.created_at - clock.now) < timedelta(milliseconds=1)

    fetched = await repo.get(1, created.id)
    assert fetched == created
    assert fetched.created_at.tzinfo is not None and fetched.expires_at.tzinfo is not None
    assert isinstance(fetched.overall_confidence, float)
    assert isinstance(fetched.recognised_items[0].grams, float)
    assert fetched.recognised_items[0].candidates[1].food_item_id is None

    raw = await buffer_db[COLLECTION].find_one({"_id": ObjectId(created.id)})
    assert set(raw) == {
        "_id",
        "userId",
        "status",
        "mealType",
        "photoUrl",
        "model",
        "overallConfidence",
        "recognisedItems",
        "createdAt",
        "expiresAt",
    }
    assert set(raw["recognisedItems"][0]) == {
        "name",
        "foodItemId",
        "candidates",
        "confidence",
        "lowConfidence",
        "grams",
        "nutrition",
        "allergyWarning",
        "corrected",
    }
    assert raw["mealType"] == "lunch" and raw["userId"] == 1
    assert set(raw["recognisedItems"][0]["candidates"][0]) == {"label", "confidence", "foodItemId"}
    assert set(raw["recognisedItems"][0]["nutrition"]) == {"kcal", "protein", "fat", "carbs"}

    new_items = [item("pizza", grams=180.0, corrected=True), item("salad")]
    updated = await repo.update_items(1, created.id, new_items)
    assert updated.recognised_items == tuple(new_items)
    assert updated.created_at == created.created_at
    assert updated.expires_at == created.expires_at
    assert await repo.get(1, created.id) == updated

    assert await repo.delete(1, created.id) is True
    assert await repo.get(1, created.id) is None
    assert await repo.delete(1, created.id) is False


# ---------------------------------------------------------------- authorization and ids


async def test_another_users_document_is_not_found(buffer_db, clock):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    created = await create(repo, user_id=1)

    assert await repo.get(2, created.id) is None
    assert await repo.update_items(2, created.id, []) is None
    assert await repo.delete(2, created.id) is False
    assert await repo.get(1, created.id) == created  # untouched


@pytest.mark.parametrize("bad_id", ["", "nope", "0" * 23, "g" * 24, "0" * 25])
async def test_invalid_object_id_is_not_found(buffer_db, clock, bad_id):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    await create(repo)

    assert await repo.get(1, bad_id) is None
    assert await repo.update_items(1, bad_id, []) is None
    assert await repo.delete(1, bad_id) is False


# ---------------------------------------------------------------- purge (B-05)


async def test_purge_user_removes_expired_too_and_nobody_elses(buffer_db, clock):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    older = await create(repo, user_id=1)
    clock.now += timedelta(hours=5)
    await create(repo, user_id=1)
    other = await create(repo, user_id=2)
    clock.now = older.expires_at + timedelta(minutes=1)  # the first one is now expired
    assert await repo.get(1, older.id) is None

    assert await repo.purge_user(1) == 2

    collection = buffer_db[COLLECTION]
    assert await collection.count_documents({"userId": 1}) == 0
    assert await collection.count_documents({}) == 1
    assert await repo.get(2, other.id) == other
    assert await repo.purge_user(1) == 0


# ---------------------------------------------------------------- photos in use


async def test_live_photo_urls_lists_unexpired_documents_of_every_user(buffer_db, clock):
    repo = MongoMealRecognitionRepository(buffer_db, clock=clock)
    expired = await create(repo, user_id=1)
    clock.now += timedelta(hours=5)
    live_1 = await create(repo, user_id=1)
    live_2 = await create(repo, user_id=2)
    clock.now = expired.expires_at + timedelta(seconds=1)

    assert await repo.live_photo_urls() == {live_1.photo_url, live_2.photo_url}


# ---------------------------------------------------------------- indexes


def script_indexes() -> list[tuple[dict[str, int], dict[str, object]]]:
    """The createIndex calls of the mongo-init script, as (keys, options)."""

    def to_json(literal: str) -> dict:
        return json.loads(re.sub(r"(\w+)\s*:", r'"\1":', literal))

    text = INIT_SCRIPT.read_text(encoding="utf-8")
    calls = re.findall(r"createIndex\(\s*(\{[^}]*\})\s*(?:,\s*(\{[^}]*\})\s*)?\)", text)
    return [(to_json(keys), to_json(options) if options else {}) for keys, options in calls]


def test_index_constants_equal_the_init_script():
    from_script = script_indexes()

    assert len(from_script) == 2
    assert from_script == [(dict(keys), options) for keys, options in INDEXES]


async def test_ensure_indexes_is_idempotent_and_matches_the_init_script(buffer_db):
    collection = buffer_db[COLLECTION]
    repo = MongoMealRecognitionRepository(buffer_db)

    await repo.ensure_indexes()
    await repo.ensure_indexes()
    ensured = await collection.index_information()

    await buffer_db.drop_collection(COLLECTION)
    for keys, options in script_indexes():  # a database created by docker compose
        await collection.create_index(list(keys.items()), **options)
    from_script = await collection.index_information()
    await repo.ensure_indexes()  # no option conflict

    assert ensured == from_script == await collection.index_information()
    assert ensured["expiresAt_1"]["expireAfterSeconds"] == 0
    assert ensured["userId_1_status_1"]["key"] == [("userId", 1), ("status", 1)]


# ---------------------------------------------------------------- app startup (main.py)


def test_app_startup_ensures_the_indexes(mongo_reachable):
    settings = get_settings().model_copy(update={"mongo_db": MONGO_TEST_DB})
    client = MongoClient(**settings.mongo_client_kwargs(), serverSelectionTimeoutMS=1000)
    collection = client[MONGO_TEST_DB][COLLECTION]
    collection.drop()  # like CI, whose MongoDB never ran the init script
    try:
        with TestClient(create_app(settings=settings)) as api:
            assert isinstance(api.app.state.recognitions, MongoMealRecognitionRepository)
        indexes = collection.index_information()
    finally:
        collection.drop()
        client.close()

    assert indexes["expiresAt_1"]["expireAfterSeconds"] == 0
    assert indexes["userId_1_status_1"]["key"] == [("userId", 1), ("status", 1)]


def test_app_starts_when_mongo_is_down(capsys):
    settings = make_settings(mongo_port=1, health_check_timeout_seconds=0.3)

    with TestClient(create_app(settings=settings)) as api:
        assert isinstance(api.app.state.recognitions, MongoMealRecognitionRepository)

    # app.core.logging writes JSON lines to stdout
    assert "MongoDB indexes not ensured: ServerSelectionTimeoutError" in capsys.readouterr().out
