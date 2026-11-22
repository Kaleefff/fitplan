"""The recognition upload flow (B-19) with fakes: no database, no ai-service."""

import asyncio
import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from app.core.errors import AppError
from app.db.repositories.meal_recognitions import (
    MealRecognition,
    Nutrition,
    RecognisedItem,
)
from app.domain.constants import PHOTO_MAX_BYTES, MealType
from app.services.ai_client import AiUnavailableError, InvalidImageError, Prediction
from app.services.recognition import LABELS_TTL_SECONDS, RecognitionService

USER = 3
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
        return (ITEM,), 0.9


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
