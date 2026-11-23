"""Meal photo recognition (B-19; FR-N1-N3; api-rules.md "Recognition").

`photo_url` is the photo's path relative to PHOTO_DIR (`meals/<user id>/<uuid>.<ext>`),
as stored; the contract has no download endpoint yet.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Response, UploadFile
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user, get_recognition_service
from app.api.v1.nutrition_logs import MacrosOut
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.db.repositories.meal_recognitions import MealRecognition, Nutrition, RecognisedItem
from app.domain.constants import MealType
from app.domain.rounding import round_half_up
from app.services.recognition import RecognitionService

router = APIRouter(prefix="/meals/recognitions", tags=["nutrition"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[RecognitionService, Depends(get_recognition_service)]
RecognitionId = Annotated[str, Path(pattern="^[0-9a-f]{24}$")]
UNAUTHORIZED = {"model": Error, "description": "Missing, expired or invalid token"}
NOT_FOUND = {"model": Error, "description": "No pending recognition of the user"}


def _macros(n: Nutrition) -> MacrosOut:
    return MacrosOut(kcal=n.kcal, protein=n.protein, fat=n.fat, carbs=n.carbs)


def _totals(items: tuple[RecognisedItem, ...]) -> MacrosOut:
    """Sum of the items' nutrition (each already rounded as nutrition logs)."""

    def total(field: str) -> float:
        summed = sum((Decimal(str(getattr(i.nutrition, field))) for i in items), Decimal(0))
        return float(round_half_up(summed, 2))

    return MacrosOut(
        kcal=total("kcal"), protein=total("protein"), fat=total("fat"), carbs=total("carbs")
    )


class RecognisedItemOut(BaseModel):
    name: str
    food_item_id: int | None
    grams: float
    confidence: float
    nutrition: MacrosOut
    corrected: bool
    low_confidence: bool
    allergy_warning: bool

    @classmethod
    def of(cls, item: RecognisedItem) -> "RecognisedItemOut":
        return cls(
            name=item.name,
            food_item_id=item.food_item_id,
            grams=item.grams,
            confidence=item.confidence,
            nutrition=_macros(item.nutrition),
            corrected=item.corrected,
            low_confidence=item.low_confidence,
            allergy_warning=item.allergy_warning,
        )


class RecognitionOut(BaseModel):
    id: str
    status: Literal["pending"]
    meal_type: MealType
    photo_url: str | None
    overall_confidence: float
    recognised_items: list[RecognisedItemOut]
    totals: MacrosOut
    created_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, r: MealRecognition) -> "RecognitionOut":
        return cls(
            id=r.id,
            status="pending",
            meal_type=MealType(r.meal_type.value),
            photo_url=r.photo_url,
            overall_confidence=r.overall_confidence,
            recognised_items=[RecognisedItemOut.of(i) for i in r.recognised_items],
            totals=_totals(r.recognised_items),
            created_at=r.created_at,
            expires_at=r.expires_at,
        )


@router.post(
    "",
    operation_id="createRecognition",
    summary="Upload a meal photo for recognition (FR-N1, FR-N2, FR-N3)",
    status_code=201,
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        413: {"model": Error, "description": "Photo over 8 MB"},
        503: {"model": Error, "description": "The AI service failed or did not answer in time"},
    },
)
async def create_recognition(
    user: User,
    service: Service,
    photo: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 8 MB")],
    meal_type: Annotated[MealType, Form()],
) -> RecognitionOut:
    raw = await photo.read()
    return RecognitionOut.of(await service.create(user.id, meal_type, raw))


@router.get(
    "/{recognition_id}",
    operation_id="getRecognition",
    summary="A pending recognition",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def get_recognition(
    recognition_id: RecognitionId, user: User, service: Service
) -> RecognitionOut:
    return RecognitionOut.of(await service.get(user.id, recognition_id))


@router.delete(
    "/{recognition_id}",
    operation_id="discardRecognition",
    summary="Discard a pending recognition and its photo",
    status_code=204,
    response_class=Response,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
async def discard_recognition(
    recognition_id: RecognitionId, user: User, service: Service
) -> Response:
    await service.discard(user.id, recognition_id)
    return Response(status_code=204)
