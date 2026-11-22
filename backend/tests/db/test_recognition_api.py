"""Meal photo recognition through the API (B-19, B-20; FR-N1-N4) on PostgreSQL with the whole
seed and the MongoDB test buffer, with ai-service replaced by a fake. The matching rules
are DB-08's (test_recognition.py); these tests check the HTTP flow, the stored photo,
the allergen flag, the 404 for other users and that an AI error stores nothing.
Skipped without PostgreSQL or MongoDB.
"""

import io
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pymongo import AsyncMongoClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.repositories.meal_recognitions import MongoMealRecognitionRepository
from app.db.repositories.recognition import Detection
from app.db.seed import load
from app.db.session import database_url
from app.main import create_app
from app.services.ai_client import AiUnavailableError, Prediction
from app.services.repositories import sql_repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db import test_account_deletion as deletion
from tests.db.conftest import MONGO_TEST_DB, delete_users
from tests.db.test_diet_plans import PROFILES
from tests.db.test_repositories import TEST_DB

migrated_db = deletion.migrated_db
buffer = deletion.buffer
_close_sync_engine = deletion._close_sync_engine

RECOGNITIONS = "/api/v1/meals/recognitions"
YOGURT, OIL = "greek yogurt, plain, whole milk", "olive oil"  # Milk allergen / none
ORIENTATION, GPS_INFO = 0x0112, 0x8825


class FakeProvider:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[bytes, str, list[str]]] = []
        self.detections = (
            Detection(YOGURT, 0.8, 150.0, ()),
            Detection(OIL, 0.25, 10.0, (("butter", 0.1),)),
        )

    async def predict(self, photo, content_type, labels):
        self.calls.append((photo, content_type, labels))
        if self.error:
            raise self.error
        return Prediction("gemini-3.1-flash-lite", "gemini-3.1-flash-lite", self.detections)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def api(migrated_db, buffer, tmp_path, provider) -> Iterator[TestClient]:
    with deletion._sync_engine().begin() as db:
        delete_users(db)
        db.execute(
            text(
                "TRUNCATE muscle_group, injury_type, allergen, food_category"
                " RESTART IDENTITY CASCADE"
            )
        )
        load(db)  # also sets recognition_label = lower(name) (A-01)
    engine = create_async_engine(database_url().set(database=TEST_DB))
    # used only on the TestClient's event loop
    mongo = AsyncMongoClient(**get_settings().mongo_client_kwargs(), serverSelectionTimeoutMS=1000)
    app = create_app(
        settings=make_settings(photo_dir=tmp_path),
        health_checker=FakeHealthChecker(),
        repositories=sql_repositories(async_sessionmaker(engine, expire_on_commit=False)),
        recognitions=MongoMealRecognitionRepository(mongo[MONGO_TEST_DB]),
        recognition_provider=provider,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(mongo.close)
        client.portal.call(engine.dispose)


def _login(api, email: str = "ann@example.com", allergy: str | None = None) -> dict:
    pair = api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "name": "A", "surname": "B"},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    profile = PROFILES["male"] | {
        "goal": "maintenance",
        "experience_level": "beginner",
        "equipment": "gym",
    }
    assert api.put("/api/v1/users/me/profile", json=profile, headers=headers).status_code == 200
    if allergy:
        with deletion._sync_engine().connect() as db:
            allergen = db.execute(
                text("SELECT id FROM allergen WHERE name = :n"), {"n": allergy}
            ).scalar_one()
        response = api.put(
            "/api/v1/users/me/allergies", json={"allergen_ids": [allergen]}, headers=headers
        )
        assert response.status_code == 200, response.text
    return headers


def _photo() -> bytes:
    exif = Image.Exif()
    exif[ORIENTATION] = 1
    exif.get_ifd(GPS_INFO)[2] = (51.0, 14.0, 0.0)  # where the photo was taken
    out = io.BytesIO()
    Image.new("RGB", (64, 48), "orange").save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _upload(api, headers, raw: bytes | None = None, meal_type: str = "lunch"):
    return api.post(
        RECOGNITIONS,
        files={"photo": ("meal.jpg", raw or _photo(), "image/jpeg")},
        data={"meal_type": meal_type},
        headers=headers,
    )


def _files(root) -> list:
    return [p for p in root.rglob("*") if p.is_file()]


def test_upload_recognises_flags_the_allergen_and_stores_the_photo(api, provider, buffer, tmp_path):
    headers = _login(api, allergy="Milk")

    started = time.perf_counter()
    response = _upload(api, headers)
    elapsed = time.perf_counter() - started

    assert response.status_code == 201, response.text
    assert elapsed <= 10  # Done of B-19 in the test setup (ai-service is faked here)
    body = response.json()
    yogurt, oil = body["recognised_items"]
    assert (yogurt["name"].lower(), yogurt["grams"], yogurt["allergy_warning"]) == (
        YOGURT,
        150.0,
        True,
    )
    assert (oil["allergy_warning"], oil["low_confidence"], oil["corrected"]) == (False, True, False)
    assert yogurt["food_item_id"] and oil["food_item_id"]
    assert body["overall_confidence"] == 0.8
    # 150 g of yogurt (97 kcal/100 g) + 10 g of oil (884 kcal/100 g) = 145.5 + 88.4
    assert (yogurt["nutrition"]["kcal"], oil["nutrition"]["kcal"]) == (145.5, 88.4)
    assert body["totals"]["kcal"] == 233.9
    assert (body["status"], body["meal_type"]) == ("pending", "lunch")
    # the photo: stored under the user's folder without EXIF; the same bytes went to the AI
    assert body["photo_url"].startswith("meals/1/") and body["photo_url"].endswith(".jpg")
    stored = (tmp_path / body["photo_url"]).read_bytes()
    with Image.open(io.BytesIO(stored)) as image:
        assert dict(image.getexif()) == {}
    sent_photo, content_type, labels = provider.calls[0]
    assert (sent_photo, content_type) == (stored, "image/jpeg")
    assert YOGURT in labels and OIL in labels
    # nothing in PostgreSQL yet; one document in the buffer
    assert buffer.count_documents({"userId": 1}) == 1
    assert api.get(f"{RECOGNITIONS}/{body['id']}", headers=headers).json() == body


def test_another_user_gets_404_and_discard_removes_document_and_photo(api, buffer, tmp_path):
    ann = _login(api)
    recognition = _upload(api, ann).json()
    bob = _login(api, "bob@example.com")
    url = f"{RECOGNITIONS}/{recognition['id']}"

    assert api.get(url, headers=bob).status_code == 404
    assert api.delete(url, headers=bob).status_code == 404
    assert api.delete(url, headers=ann).status_code == 204

    assert api.get(url, headers=ann).status_code == 404
    assert buffer.count_documents({}) == 0
    assert _files(tmp_path) == []
    assert api.get(f"{RECOGNITIONS}/{'0' * 24}", headers=ann).status_code == 404
    assert api.get(f"{RECOGNITIONS}/not-an-id", headers=ann).status_code == 422


def test_an_ai_error_is_503_and_stores_nothing(api, provider, buffer, tmp_path):
    headers = _login(api)
    provider.error = AiUnavailableError()

    response = _upload(api, headers)

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "ai_unavailable"
    assert buffer.count_documents({}) == 0
    assert _files(tmp_path) == []


def test_invalid_uploads_are_rejected_before_the_ai(api, provider):
    headers = _login(api)

    not_a_photo = _upload(api, headers, raw=b"%PDF-1.7 not a photo")
    no_meal_type = api.post(
        RECOGNITIONS, files={"photo": ("m.jpg", _photo(), "image/jpeg")}, headers=headers
    )

    assert not_a_photo.status_code == 422
    assert [(d["field"], d["code"]) for d in not_a_photo.json()["details"]] == [
        ("body.photo", "invalid_image")
    ]
    assert no_meal_type.status_code == 422
    assert provider.calls == []


# ---------------------------------------------------------------- review and confirm (B-20)


def _food_id(name: str) -> int:
    with deletion._sync_engine().connect() as db:
        return db.execute(
            text("SELECT id FROM food_item WHERE name = :n"), {"n": name}
        ).scalar_one()


def test_review_then_confirm_writes_the_log_and_deletes_the_document(
    api, provider, buffer, tmp_path
):
    headers = _login(api)
    provider.detections = (
        Detection(YOGURT, 0.8, 150.0, ()),
        Detection(OIL, 0.25, 10.0, ()),
        Detection("dragon fruit", 0.5, None, ()),  # no food matches it
    )
    recognition = _upload(api, headers).json()
    url = f"{RECOGNITIONS}/{recognition['id']}"
    assert [i["food_item_id"] is None for i in recognition["recognised_items"]] == [
        False,
        False,
        True,
    ]

    unmatched = api.post(f"{url}/confirm", headers=headers)
    assert unmatched.status_code == 422, unmatched.text
    assert [(d["field"], d["code"]) for d in unmatched.json()["details"]] == [
        ("recognised_items.2.food_item_id", "missing")
    ]

    # grams of the yogurt: 200 g x 97 kcal/100 g = 194 kcal, corrected
    grams = api.patch(f"{url}/items/0", json={"grams": 200}, headers=headers)
    assert grams.status_code == 200, grams.text
    yogurt = grams.json()["recognised_items"][0]
    assert (yogurt["grams"], yogurt["nutrition"]["kcal"], yogurt["corrected"]) == (
        200.0,
        194.0,
        True,
    )
    # the user picks a product for the unknown item
    rice = _food_id("White rice, cooked")
    picked = api.patch(f"{url}/items/2", json={"food_item_id": rice, "grams": 120}, headers=headers)
    assert picked.json()["recognised_items"][2]["name"] == "White rice, cooked"
    # oil again is a duplicate; removing the oil works; another product is added
    oil = recognition["recognised_items"][1]["food_item_id"]
    duplicate = api.post(f"{url}/items", json={"food_item_id": oil, "grams": 5}, headers=headers)
    assert duplicate.status_code == 422
    assert api.delete(f"{url}/items/1", headers=headers).status_code == 200
    banana = _food_id("Banana")
    added = api.post(f"{url}/items", json={"food_item_id": banana, "grams": 100}, headers=headers)
    assert added.status_code == 200, added.text
    reviewed = added.json()
    assert [i["food_item_id"] for i in reviewed["recognised_items"]] == [
        yogurt["food_item_id"],
        rice,
        banana,
    ]
    assert api.patch(f"{url}/items/9", json={"grams": 1}, headers=headers).status_code == 404
    bob = _login(api, "bob@example.com")
    assert api.post(f"{url}/confirm", headers=bob).status_code == 404

    confirmed = api.post(f"{url}/confirm", json={"hunger_level_before": 4}, headers=headers)

    assert confirmed.status_code == 201, confirmed.text
    log = confirmed.json()
    assert log["actual_cals"] == reviewed["totals"]["kcal"]
    assert (log["meal_photo_url"], log["meal_type"], log["hunger_level_before"]) == (
        recognition["photo_url"],
        "lunch",
        4,
    )
    assert (log["ai_confidence"], log["ai_was_edited"]) == (0.8, True)
    assert sorted(i["food_item_id"] for i in log["items"]) == sorted(
        [yogurt["food_item_id"], rice, banana]
    )
    # the document is gone, the photo of a confirmed meal stays (api-rules.md)
    assert api.get(url, headers=headers).status_code == 404
    assert buffer.count_documents({}) == 0
    assert (tmp_path / recognition["photo_url"]).exists()
    logs = api.get("/api/v1/nutrition-logs", headers=headers).json()
    assert [entry["id"] for entry in logs["items"]] == [log["id"]]
