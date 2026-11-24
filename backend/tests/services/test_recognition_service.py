"""The recognition upload (B-19) and review (B-20) flows with fakes: no database, no
ai-service."""

import asyncio
import dataclasses
import io
from datetime import UTC, date, datetime, timedelta

import pytest
from PIL import Image

from app.core.errors import AppError
from app.db.repositories.meal_recognitions import (
    MealRecognition,
    Nutrition,
    RecognisedItem,
)
from app.db.repositories.nutrition_logs import ClientUuidDeletedError, DuplicateFoodError
from app.db.repositories.recognition import (
    FoodNotAvailableError,
    PricedItem,
    UnmatchedItemError,
)
from app.domain.constants import PHOTO_MAX_BYTES, MealType
from app.services.ai_client import AiUnavailableError, InvalidImageError, Prediction
from app.services.recognition import (
    LABELS_TTL_SECONDS,
    MANUAL_ITEM_CONFIDENCE,
    RecognitionService,
)

USER = 3
FOODS = {5: ("Basmati rice, cooked", 1.3), 9: ("Olive oil", 8.84)}  # id: (name, kcal/g)
TODAY = date(2026, 11, 22)
ITEM = RecognisedItem(
    name="Basmati rice, cooked",
    food_item_id=5,
    candidates=(),
    confidence=0.9,
    low_confidence=False,
    grams=180.0,
    nutrition=Nutrition(234.0, 5.0, 0.5, 50.0),
    allergy_warning=False,
    corrected=False,
)


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(out, format="JPEG")
    return out.getvalue()


class FakeStore:
    def __init__(self, labels=("basmati rice, cooked",)):
        self.labels = list(labels)
        self.label_calls = 0
        self.matched = None

    async def active_labels(self):
        self.label_calls += 1
        return self.labels

    async def match(self, user_id, detections):
        self.matched = (user_id, detections)
        return self.items, 0.9

    items = (ITEM,)
    confirm_result: object = "log"

    async def price_item(self, user_id, food_item_id, grams):
        if food_item_id not in FOODS:
            raise FoodNotAvailableError(food_item_id)
        name, kcal_per_g = FOODS[food_item_id]
        return PricedItem(
            food_item_id, name, float(grams), Nutrition(kcal_per_g * grams, 0, 0, 0), False
        )

    async def confirm(self, buffer, user_id, recognition_id, log_date, before, after):
        self.confirmed = (user_id, recognition_id, log_date, before, after)
        if isinstance(self.confirm_result, Exception):
            raise self.confirm_result
        return self.confirm_result


class FakeBuffer:
    def __init__(self, fail=False):
        self.docs: dict[str, MealRecognition] = {}
        self.fail = fail

    async def create(self, user_id, meal_type, photo_url, model, overall_confidence, items):
        if self.fail:
            raise RuntimeError("mongo down")
        now = datetime.now(UTC)
        doc = MealRecognition(
            id=f"{len(self.docs):024x}",
            user_id=user_id,
            status="pending",
            meal_type=meal_type,
            photo_url=photo_url,
            model=model,
            overall_confidence=overall_confidence,
            recognised_items=tuple(items),
            created_at=now,
            expires_at=now + timedelta(hours=6),
        )
        self.docs[doc.id] = doc
        return doc

    async def get(self, user_id, recognition_id):
        doc = self.docs.get(recognition_id)
        return doc if doc and doc.user_id == user_id else None

    async def delete(self, user_id, recognition_id):
        return self.docs.pop(recognition_id, None) is not None

    async def update_items(self, user_id, recognition_id, items):
        doc = await self.get(user_id, recognition_id)
        if doc is None:
            return None
        self.docs[recognition_id] = dataclasses.replace(doc, recognised_items=tuple(items))
        return self.docs[recognition_id]


class FakeProvider:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def predict(self, photo, content_type, labels):
        self.calls.append((content_type, labels))
        if self.error:
            raise self.error
        return Prediction("gemini-3.1-flash-lite", "v1", ())


def _service(tmp_path, store=None, buffer=None, provider=None, clock=lambda: 0.0):
    buffer = buffer or FakeBuffer()
    service = RecognitionService(
        store or FakeStore(), lambda: buffer, provider or FakeProvider(), lambda: tmp_path, clock
    )
    return service, buffer


def _status(coroutine) -> int:
    with pytest.raises(AppError) as error:
        asyncio.run(coroutine)
    return error.value.status_code


def _photos(tmp_path) -> list:
    return [p for p in tmp_path.rglob("*") if p.is_file()]


def test_upload_stores_the_photo_and_a_pending_document(tmp_path):
    store, provider = FakeStore(), FakeProvider()
    service, _ = _service(tmp_path, store=store, provider=provider)

    recognition = asyncio.run(service.create(USER, MealType.LUNCH, _jpeg()))

    assert provider.calls == [("image/jpeg", ["basmati rice, cooked"])]
    assert store.matched[0] == USER
    assert recognition.recognised_items == (ITEM,)
    assert recognition.photo_url.startswith(f"meals/{USER}/")
    assert (tmp_path / recognition.photo_url).exists()
    assert asyncio.run(service.get(USER, recognition.id)) == recognition
    assert _status(service.get(USER + 1, recognition.id)) == 404


@pytest.mark.parametrize(
    ("raw", "status"),
    [(b"x" * (PHOTO_MAX_BYTES + 1), 413), (b"not a photo", 422)],
    # short ids: pytest would name the case after the bytes (megabytes), and Windows
    # refuses PYTEST_CURRENT_TEST above 32767 characters
    ids=["too_large", "unreadable"],
)
def test_too_large_or_unreadable_photos_never_reach_the_ai(tmp_path, raw, status):
    provider = FakeProvider()
    service, _ = _service(tmp_path, provider=provider)

    assert _status(service.create(USER, MealType.LUNCH, raw)) == status
    assert provider.calls == [] and _photos(tmp_path) == []


@pytest.mark.parametrize(
    ("error", "status"), [(AiUnavailableError(), 503), (InvalidImageError(), 422)]
)
def test_an_ai_error_stores_nothing(tmp_path, error, status):
    service, buffer = _service(tmp_path, provider=FakeProvider(error))

    assert _status(service.create(USER, MealType.LUNCH, _jpeg())) == status
    assert buffer.docs == {} and _photos(tmp_path) == []


def test_without_labels_the_ai_is_not_called(tmp_path):
    provider = FakeProvider()
    service, _ = _service(tmp_path, store=FakeStore(labels=()), provider=provider)

    assert _status(service.create(USER, MealType.LUNCH, _jpeg())) == 503
    assert provider.calls == []


def test_a_failed_document_write_removes_the_photo(tmp_path):
    service, _ = _service(tmp_path, buffer=FakeBuffer(fail=True))

    with pytest.raises(RuntimeError):
        asyncio.run(service.create(USER, MealType.LUNCH, _jpeg()))
    assert _photos(tmp_path) == []


def test_labels_are_cached_for_ten_minutes(tmp_path):
    now = [0.0]
    store = FakeStore()
    service, _ = _service(tmp_path, store=store, clock=lambda: now[0])

    asyncio.run(service.labels())
    now[0] = LABELS_TTL_SECONDS - 1
    asyncio.run(service.labels())
    assert store.label_calls == 1
    now[0] = LABELS_TTL_SECONDS
    asyncio.run(service.labels())
    assert store.label_calls == 2


def test_discard_deletes_the_document_and_the_photo(tmp_path):
    service, buffer = _service(tmp_path)
    recognition = asyncio.run(service.create(USER, MealType.DINNER, _jpeg()))

    assert _status(service.discard(USER + 1, recognition.id)) == 404
    asyncio.run(service.discard(USER, recognition.id))

    assert buffer.docs == {} and _photos(tmp_path) == []
    assert _status(service.discard(USER, recognition.id)) == 404


# ---------------------------------------------------------------- review (B-20)

UNMATCHED = dataclasses.replace(
    ITEM, name="dragon fruit", food_item_id=None, grams=0.0, nutrition=Nutrition(0, 0, 0, 0)
)


def _uploaded(tmp_path, items=(ITEM,)):
    store = FakeStore()
    store.items = tuple(items)
    service, _ = _service(tmp_path, store=store)
    recognition = asyncio.run(service.create(USER, MealType.LUNCH, _jpeg()))
    return service, store, recognition.id


def test_an_added_product_is_certain_corrected_and_priced(tmp_path):
    service, _, rid = _uploaded(tmp_path)

    items = asyncio.run(service.add_item(USER, rid, 9, 10.0)).recognised_items

    added = items[-1]
    assert (added.name, added.food_item_id, added.grams, added.nutrition.kcal) == (
        "Olive oil",
        9,
        10.0,
        88.4,
    )
    assert (added.confidence, added.low_confidence, added.corrected) == (
        MANUAL_ITEM_CONFIDENCE,
        False,
        True,
    )
    assert _status(service.add_item(USER, rid, 5, 50.0)) == 422  # rice is already listed
    assert _status(service.add_item(USER, rid, 404, 50.0)) == 422  # unknown food
    assert _status(service.add_item(USER + 1, rid, 9, 10.0)) == 404


def test_new_grams_reprice_and_a_new_product_renames(tmp_path):
    service, _, rid = _uploaded(tmp_path)

    grams = asyncio.run(service.update_item(USER, rid, 0, None, 200.0)).recognised_items[0]
    food = asyncio.run(service.update_item(USER, rid, 0, 9, None)).recognised_items[0]

    assert (grams.name, grams.grams, grams.nutrition.kcal, grams.corrected) == (
        ITEM.name,
        200.0,
        260.0,
        True,
    )
    assert (food.name, food.food_item_id, food.grams) == ("Olive oil", 9, 200.0)
    assert _status(service.update_item(USER, rid, 1, None, 5.0)) == 404  # no such index


def test_grams_alone_on_an_unmatched_item_round_half_up(tmp_path):
    service, _, rid = _uploaded(tmp_path, items=(UNMATCHED,))

    item = asyncio.run(service.update_item(USER, rid, 0, None, 12.25)).recognised_items[0]

    assert (item.grams, item.food_item_id, item.nutrition.kcal, item.corrected) == (
        12.3,
        None,
        0,
        True,
    )


def test_delete_item_keeps_the_others_in_order(tmp_path):
    second = dataclasses.replace(ITEM, name="second", food_item_id=9)
    service, _, rid = _uploaded(tmp_path, items=(ITEM, second))

    items = asyncio.run(service.delete_item(USER, rid, 0)).recognised_items

    assert [i.name for i in items] == ["second"]
    assert _status(service.delete_item(USER, rid, 1)) == 404


def test_confirm_defaults_to_today_and_refuses_after_tomorrow(tmp_path):
    service, store, rid = _uploaded(tmp_path)

    assert asyncio.run(service.confirm(USER, rid, None, 3, None, TODAY)) == "log"
    assert store.confirmed == (USER, rid, TODAY, 3, None)
    later = TODAY + timedelta(days=2)
    assert _status(service.confirm(USER, rid, later, None, None, TODAY)) == 422


@pytest.mark.parametrize(
    ("result", "status", "field"),
    [
        (None, 404, None),
        (UnmatchedItemError(1), 422, "recognised_items.1.food_item_id"),
        (DuplicateFoodError(0), 422, "recognised_items.0.food_item_id"),
        (ClientUuidDeletedError(), 409, None),
    ],
)
def test_confirm_errors(tmp_path, result, status, field):
    service, store, rid = _uploaded(tmp_path)
    store.confirm_result = result

    with pytest.raises(AppError) as error:
        asyncio.run(service.confirm(USER, rid, None, None, None, TODAY))

    assert error.value.status_code == status
    if field:
        assert error.value.details[0]["field"] == field
