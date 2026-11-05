"""MongoDB buffer of unconfirmed meal recognitions (DB-07, FR-N4; docs/database/mongo_buffer.md).

The camelCase document fields are mapped to the snake_case dataclasses only here. Every
read, update and delete of one document filters the owner and `expiresAt > now`: the TTL
monitor runs about once a minute, so an expired document may still be stored, and it
must behave exactly like a missing one.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.codec_options import CodecOptions
from bson.errors import InvalidId
from pymongo import ASCENDING, ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from app.db.enums import MealType
from app.domain.constants import RECOGNITION_EXPIRY_HOURS

COLLECTION = "meal_recognitions"
RECOGNITION_TTL = timedelta(hours=RECOGNITION_EXPIRY_HOURS)
PENDING = "pending"

# Same keys and options as database/mongo-init/01_meal_recognitions.js, so ensure_indexes
# on a database created by docker compose is a no-op and never an option conflict.
INDEXES: tuple[tuple[list[tuple[str, int]], dict[str, Any]], ...] = (
    ([("expiresAt", ASCENDING)], {"expireAfterSeconds": 0}),
    ([("userId", ASCENDING), ("status", ASCENDING)], {}),
)

_CODEC = CodecOptions(tz_aware=True, tzinfo=UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RecognitionModel:
    name: str
    version: str


@dataclass(frozen=True)
class Candidate:
    label: str
    confidence: float
    food_item_id: int | None


@dataclass(frozen=True)
class Nutrition:
    kcal: float
    protein: float
    fat: float
    carbs: float


@dataclass(frozen=True)
class RecognisedItem:
    name: str
    food_item_id: int | None
    candidates: tuple[Candidate, ...]
    confidence: float
    low_confidence: bool
    grams: float
    nutrition: Nutrition
    allergy_warning: bool
    corrected: bool


@dataclass(frozen=True)
class MealRecognition:
    id: str
    user_id: int
    status: str
    meal_type: MealType
    photo_url: str
    model: RecognitionModel
    overall_confidence: float
    recognised_items: tuple[RecognisedItem, ...]
    created_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------- mapping


def _item_to_doc(item: RecognisedItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "foodItemId": item.food_item_id,
        "candidates": [
            {"label": c.label, "confidence": float(c.confidence), "foodItemId": c.food_item_id}
            for c in item.candidates
        ],
        "confidence": float(item.confidence),
        "lowConfidence": item.low_confidence,
        "grams": float(item.grams),
        "nutrition": {
            "kcal": float(item.nutrition.kcal),
            "protein": float(item.nutrition.protein),
            "fat": float(item.nutrition.fat),
            "carbs": float(item.nutrition.carbs),
        },
        "allergyWarning": item.allergy_warning,
        "corrected": item.corrected,
    }


def _item_from_doc(doc: dict[str, Any]) -> RecognisedItem:
    nutrition = doc["nutrition"]
    return RecognisedItem(
        name=doc["name"],
        food_item_id=doc["foodItemId"],
        candidates=tuple(
            Candidate(label=c["label"], confidence=c["confidence"], food_item_id=c["foodItemId"])
            for c in doc["candidates"]
        ),
        confidence=doc["confidence"],
        low_confidence=doc["lowConfidence"],
        grams=doc["grams"],
        nutrition=Nutrition(
            kcal=nutrition["kcal"],
            protein=nutrition["protein"],
            fat=nutrition["fat"],
            carbs=nutrition["carbs"],
        ),
        allergy_warning=doc["allergyWarning"],
        corrected=doc["corrected"],
    )


def _items_to_doc(items: Iterable[RecognisedItem]) -> list[dict[str, Any]]:
    return [_item_to_doc(item) for item in items]


def _from_doc(doc: dict[str, Any]) -> MealRecognition:
    return MealRecognition(
        id=str(doc["_id"]),
        user_id=doc["userId"],
        status=doc["status"],
        meal_type=MealType(doc["mealType"]),
        photo_url=doc["photoUrl"],
        model=RecognitionModel(name=doc["model"]["name"], version=doc["model"]["version"]),
        overall_confidence=doc["overallConfidence"],
        recognised_items=tuple(_item_from_doc(item) for item in doc["recognisedItems"]),
        created_at=doc["createdAt"],
        expires_at=doc["expiresAt"],
    )


def _object_id(recognition_id: str) -> ObjectId | None:
    try:
        return ObjectId(recognition_id)
    except (InvalidId, TypeError):
        return None


def _to_bson_precision(moment: datetime) -> datetime:
    """BSON dates hold milliseconds; cut before writing so the returned record equals a read."""
    moment = moment.astimezone(UTC)
    return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


# ---------------------------------------------------------------- repository


class MongoMealRecognitionRepository:
    def __init__(self, db: AsyncDatabase, clock: Callable[[], datetime] = utc_now) -> None:
        self._collection: AsyncCollection = db.get_collection(COLLECTION, codec_options=_CODEC)
        self._clock = clock

    async def ensure_indexes(self) -> None:
        for keys, options in INDEXES:
            await self._collection.create_index(keys, **options)

    def _live(self, user_id: int, oid: ObjectId) -> dict[str, Any]:
        return {"_id": oid, "userId": user_id, "expiresAt": {"$gt": self._clock()}}

    async def create(
        self,
        user_id: int,
        meal_type: MealType,
        photo_url: str,
        model: RecognitionModel,
        overall_confidence: float,
        items: Iterable[RecognisedItem],
    ) -> MealRecognition:
        created_at = _to_bson_precision(self._clock())
        doc: dict[str, Any] = {
            "userId": user_id,
            "status": PENDING,
            "mealType": MealType(meal_type).value,
            "photoUrl": photo_url,
            "model": {"name": model.name, "version": model.version},
            "overallConfidence": float(overall_confidence),
            "recognisedItems": _items_to_doc(items),
            "createdAt": created_at,
            "expiresAt": created_at + RECOGNITION_TTL,
        }
        result = await self._collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return _from_doc(doc)

    async def get(self, user_id: int, recognition_id: str) -> MealRecognition | None:
        oid = _object_id(recognition_id)
        if oid is None:
            return None
        doc = await self._collection.find_one(self._live(user_id, oid))
        return None if doc is None else _from_doc(doc)

    async def update_items(
        self, user_id: int, recognition_id: str, items: Iterable[RecognisedItem]
    ) -> MealRecognition | None:
        oid = _object_id(recognition_id)
        if oid is None:
            return None
        doc = await self._collection.find_one_and_update(
            self._live(user_id, oid),
            {"$set": {"recognisedItems": _items_to_doc(items)}},
            return_document=ReturnDocument.AFTER,
        )
        return None if doc is None else _from_doc(doc)

    async def delete(self, user_id: int, recognition_id: str) -> bool:
        oid = _object_id(recognition_id)
        if oid is None:
            return False
        result = await self._collection.delete_one(self._live(user_id, oid))
        return result.deleted_count == 1

    async def purge_user(self, user_id: int) -> int:
        """Account deletion (B-05, FR-U5): every document of the user, expired ones too."""
        result = await self._collection.delete_many({"userId": user_id})
        return result.deleted_count

    async def live_photo_urls(self) -> set[str]:
        """`photoUrl` of every unexpired document of every user, for the photo cleanup job."""
        cursor = self._collection.find(
            {"expiresAt": {"$gt": self._clock()}}, projection={"photoUrl": True, "_id": False}
        )
        return {doc["photoUrl"] async for doc in cursor if doc.get("photoUrl")}
