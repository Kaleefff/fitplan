"""Meal photo recognition (B-19; FR-N1-N3; algorithms.md 11; api-rules.md "Recognition").

Upload: the photo is checked and stripped of metadata, sent with the active labels to
ai-service, the detections are matched to foods (DB-08) and one pending document is
written to the MongoDB buffer (6 h). Nothing goes to PostgreSQL before confirmation. An
AI error or timeout is returned directly: no document is stored and the photo is not kept.
"""

import asyncio
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.db.repositories.meal_recognitions import (
    MealRecognition,
    RecognisedItem,
    RecognitionModel,
)
from app.db.repositories.recognition import Detection
from app.domain.constants import PHOTO_MAX_BYTES, MealType
from app.services.ai_client import AiUnavailableError, InvalidImageError, RecognitionProvider
from app.services.photos import InvalidPhotoError, prepare_photo, remove_photo, store_photo

# TODO(questions.md [A-01] labels-source): proposed default, labels cached for 10 minutes
LABELS_TTL_SECONDS = 600


class RecognitionStore(Protocol):
    async def active_labels(self) -> list[str]: ...

    async def match(
        self, user_id: int, detections: Sequence[Detection]
    ) -> tuple[tuple[RecognisedItem, ...], float]: ...


class RecognitionBuffer(Protocol):
    async def create(
        self,
        user_id: int,
        meal_type: MealType,
        photo_url: str,
        model: RecognitionModel,
        overall_confidence: float,
        items: Iterable[RecognisedItem],
    ) -> MealRecognition: ...

    async def get(self, user_id: int, recognition_id: str) -> MealRecognition | None: ...

    async def delete(self, user_id: int, recognition_id: str) -> bool: ...


def _invalid_photo() -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "The photo must be a JPEG, PNG or WebP image",
        [{"field": "body.photo", "code": "invalid_image", "message": "Not a readable photo"}],
    )


def _ai_unavailable() -> AppError:
    return AppError(
        503,
        ErrorCode.AI_UNAVAILABLE,
        "Meal recognition is not available right now, try again",
    )


class RecognitionService:
    def __init__(
        self,
        store: RecognitionStore,
        buffer: Callable[[], RecognitionBuffer],
        provider: RecognitionProvider,
        photo_dir: Callable[[], Path],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._buffer = buffer
        self._provider = provider
        self._photo_dir = photo_dir
        self._clock = clock
        self._labels: list[str] = []
        self._labels_at: float | None = None
        self._labels_lock = asyncio.Lock()

    async def labels(self) -> list[str]:
        async with self._labels_lock:
            now = self._clock()
            if self._labels_at is None or now - self._labels_at >= LABELS_TTL_SECONDS:
                self._labels = await self._store.active_labels()
                self._labels_at = now
            return self._labels

    async def create(self, user_id: int, meal_type: MealType, raw: bytes) -> MealRecognition:
        if len(raw) > PHOTO_MAX_BYTES:
            raise AppError(
                413,
                ErrorCode.PAYLOAD_TOO_LARGE,
                "The photo may be at most 8 MB",
                [{"field": "body.photo", "code": "too_large", "message": "At most 8 MB"}],
            )
        try:
            photo = await asyncio.to_thread(prepare_photo, raw)
        except InvalidPhotoError:
            raise _invalid_photo() from None

        labels = await self.labels()
        if not labels:  # no food catalogue to match against
            raise _ai_unavailable()
        try:
            prediction = await self._provider.predict(photo.data, photo.content_type, labels)
        except InvalidImageError:
            raise _invalid_photo() from None
        except AiUnavailableError:
            raise _ai_unavailable() from None
        items, overall = await self._store.match(user_id, prediction.detections)

        photo_dir = self._photo_dir()
        photo_url = await asyncio.to_thread(store_photo, photo_dir, user_id, photo)
        try:
            return await self._buffer().create(
                user_id,
                meal_type,
                photo_url,
                RecognitionModel(prediction.model_name, prediction.model_version),
                overall,
                items,
            )
        except BaseException:
            await asyncio.to_thread(remove_photo, photo_dir, photo_url)
            raise

    async def get(self, user_id: int, recognition_id: str) -> MealRecognition:
        """404 for a missing, expired or another user's recognition."""
        recognition = await self._buffer().get(user_id, recognition_id)
        if recognition is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
        return recognition

    async def discard(self, user_id: int, recognition_id: str) -> None:
        """Deletes the document, then its photo (FR-N4); 404 like `get`. A photo whose
        delete fails is left to the cleanup job: no document references it any more."""
        recognition = await self.get(user_id, recognition_id)
        if not await self._buffer().delete(user_id, recognition.id):
            raise AppError(404, ErrorCode.NOT_FOUND, "Not found")  # confirmed meanwhile
        await asyncio.to_thread(remove_photo, self._photo_dir(), recognition.photo_url)
