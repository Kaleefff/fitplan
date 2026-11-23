"""Meal photo recognition (B-19, B-20; FR-N1-N4; algorithms.md 11; api-rules.md
"Recognition").

Upload: the photo is checked and stripped of metadata, sent with the active labels to
ai-service, the detections are matched to foods (DB-08) and one pending document is
written to the MongoDB buffer (6 h). Nothing goes to PostgreSQL before confirmation. An
AI error or timeout is returned directly: no document is stored and the photo is not kept.

Review (B-20): add, remove or replace items and change grams; every change reprices the
item from `food_item` and sets `corrected`. Confirm writes the nutrition log in one
PostgreSQL transaction, then deletes the document (DB-08).
"""

import asyncio
import dataclasses
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.db.repositories.meal_recognitions import (
    MealRecognition,
    RecognisedItem,
    RecognitionModel,
)
from app.db.repositories.nutrition_logs import (
    ClientUuidDeletedError,
    DuplicateFoodError,
    ItemError,
    LogTooLargeError,
    NutritionLogView,
    UnknownFoodError,
    ZeroGramsError,
)
from app.db.repositories.recognition import (
    MAX_ITEM_GRAMS,
    Detection,
    FoodNotAvailableError,
    NoItemsError,
    PricedItem,
    UnmatchedItemError,
)
from app.domain.constants import PHOTO_MAX_BYTES, MealType
from app.domain.rounding import round_half_up
from app.services.ai_client import AiUnavailableError, InvalidImageError, RecognitionProvider
from app.services.photos import InvalidPhotoError, prepare_photo, remove_photo, store_photo

# TODO(questions.md [A-01] labels-source): proposed default, labels cached for 10 minutes
LABELS_TTL_SECONDS = 600
# TODO(questions.md [B-20] manual-item-confidence): an item the user adds is certain
MANUAL_ITEM_CONFIDENCE = 1.0


class RecognitionStore(Protocol):
    async def active_labels(self) -> list[str]: ...

    async def match(
        self, user_id: int, detections: Sequence[Detection]
    ) -> tuple[tuple[RecognisedItem, ...], float]: ...

    async def price_item(
        self, user_id: int, food_item_id: int, grams: float | Decimal
    ) -> PricedItem: ...

    async def confirm(
        self,
        buffer: "RecognitionBuffer",
        user_id: int,
        recognition_id: str,
        log_date: date,
        hunger_before: int | None,
        hunger_after: int | None,
    ) -> NutritionLogView | None: ...


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

    async def update_items(
        self, user_id: int, recognition_id: str, items: Iterable[RecognisedItem]
    ) -> MealRecognition | None: ...


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


def _not_found() -> AppError:
    return AppError(404, ErrorCode.NOT_FOUND, "Not found")


def _invalid(field: str, code: str, message: str) -> AppError:
    detail = {"field": field, "code": code, "message": message}
    return AppError(422, ErrorCode.VALIDATION_ERROR, message, [detail])


def _confirm_error(error: Exception) -> AppError:
    """DB-08's and DB-09's errors; an item's field is its place in `recognised_items`."""
    at = f"recognised_items.{getattr(error, 'index', 0)}"
    if isinstance(error, NoItemsError):
        return _invalid("recognised_items", "missing", "Add at least one product")
    if isinstance(error, UnmatchedItemError):
        return _invalid(f"{at}.food_item_id", "missing", "Pick a product for this item")
    if isinstance(error, DuplicateFoodError):
        return _invalid(f"{at}.food_item_id", "duplicate", "The product is listed twice")
    if isinstance(error, UnknownFoodError):
        return _invalid(f"{at}.food_item_id", "not_found", "The product is no longer available")
    if isinstance(error, ZeroGramsError):
        return _invalid(f"{at}.grams", "invalid_value", "Grams round to 0.0")
    if isinstance(error, LogTooLargeError):
        return _invalid("recognised_items", "too_large", "A total of the meal is above 9999.99")
    message = "This recognition was confirmed and its log deleted"
    return AppError(409, ErrorCode.CONFLICT, message, [{"code": "conflict", "message": message}])


CONFIRM_ERRORS = (NoItemsError, ItemError, LogTooLargeError, ClientUuidDeletedError)


def _priced(item: RecognisedItem, priced: PricedItem, *, rename: bool) -> RecognisedItem:
    return dataclasses.replace(
        item,
        name=priced.name if rename else item.name,
        food_item_id=priced.food_item_id,
        grams=priced.grams,
        nutrition=priced.nutrition,
        allergy_warning=priced.allergy_warning,
        corrected=True,
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

    # ------------------------------------------------------------ review (B-20)

    async def _price(self, user_id: int, food_item_id: int, grams: float) -> PricedItem:
        try:
            return await self._store.price_item(user_id, food_item_id, grams)
        except FoodNotAvailableError:
            raise _invalid("body.food_item_id", "not_found", "Unknown or inactive food") from None

    @staticmethod
    def _no_duplicate(items: Sequence[RecognisedItem], food_item_id: int, skip: int) -> None:
        """api-rules.md "Logs": the same food twice in one log is 422 `duplicate`; checked
        here already so the user merges the grams before confirming."""
        if any(i != skip and item.food_item_id == food_item_id for i, item in enumerate(items)):
            raise _invalid("body.food_item_id", "duplicate", "The product is already listed")

    async def _save(
        self, user_id: int, recognition: MealRecognition, items: Iterable[RecognisedItem]
    ) -> MealRecognition:
        saved = await self._buffer().update_items(user_id, recognition.id, items)
        if saved is None:  # expired, discarded or confirmed meanwhile
            raise _not_found()
        return saved

    async def add_item(
        self, user_id: int, recognition_id: str, food_item_id: int, grams: float
    ) -> MealRecognition:
        """A product the model missed, appended at the end."""
        recognition = await self.get(user_id, recognition_id)
        items = recognition.recognised_items
        self._no_duplicate(items, food_item_id, skip=-1)
        priced = await self._price(user_id, food_item_id, grams)
        item = RecognisedItem(
            name=priced.name,
            food_item_id=priced.food_item_id,
            candidates=(),
            confidence=MANUAL_ITEM_CONFIDENCE,
            low_confidence=False,
            grams=priced.grams,
            nutrition=priced.nutrition,
            allergy_warning=priced.allergy_warning,
            corrected=True,
        )
        return await self._save(user_id, recognition, (*items, item))

    def _item(self, recognition: MealRecognition, index: int) -> RecognisedItem:
        if not 0 <= index < len(recognition.recognised_items):
            raise _not_found()
        return recognition.recognised_items[index]

    async def update_item(
        self,
        user_id: int,
        recognition_id: str,
        index: int,
        food_item_id: int | None,
        grams: float | None,
    ) -> MealRecognition:
        """A new product, new grams or both; nutrition and allergy_warning are recomputed.
        Grams alone on an item without a product only store the grams (nutrition stays 0
        until a product is picked)."""
        recognition = await self.get(user_id, recognition_id)
        items = list(recognition.recognised_items)
        item = self._item(recognition, index)
        new_grams = item.grams if grams is None else grams
        food = food_item_id if food_item_id is not None else item.food_item_id
        if food is None:
            # rounded and clamped as DB-08 does (algorithms.md 11)
            quantised = round_half_up(min(Decimal(str(new_grams)), MAX_ITEM_GRAMS), 1)
            items[index] = dataclasses.replace(item, grams=float(quantised), corrected=True)
        else:
            if food_item_id is not None:
                self._no_duplicate(items, food_item_id, skip=index)
            priced = await self._price(user_id, food, new_grams)
            items[index] = _priced(item, priced, rename=food_item_id is not None)
        return await self._save(user_id, recognition, items)

    async def delete_item(self, user_id: int, recognition_id: str, index: int) -> MealRecognition:
        recognition = await self.get(user_id, recognition_id)
        self._item(recognition, index)
        items = [item for i, item in enumerate(recognition.recognised_items) if i != index]
        return await self._save(user_id, recognition, items)

    async def confirm(
        self,
        user_id: int,
        recognition_id: str,
        log_date: date | None,
        hunger_before: int | None,
        hunger_after: int | None,
        today: date,
    ) -> NutritionLogView:
        """`today` in the user's time zone: the default date, and the date may be at most
        tomorrow (api-rules.md "Dates")."""
        log_date = log_date or today
        if log_date > today + timedelta(days=1):
            raise _invalid("body.log_date", "future_date", "Date is after tomorrow")
        try:
            log = await self._store.confirm(
                self._buffer(), user_id, recognition_id, log_date, hunger_before, hunger_after
            )
        except CONFIRM_ERRORS as error:
            raise _confirm_error(error) from None
        if log is None:
            raise _not_found()
        return log
