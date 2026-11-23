"""Meal photo recognition (B-19, B-20; FR-N1-N4; api-rules.md "Recognition").

`photo_url` is the photo's path relative to PHOTO_DIR (`meals/<user id>/<uuid>.<ext>`),
as stored; the contract has no download endpoint yet.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Response, UploadFile
from pydantic import BaseModel, Field, model_validator

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_recognition_service,
    get_user_repository,
)
from app.api.v1.nutrition_logs import MacrosOut, NutritionLogOut, _timezone
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.db.repositories.meal_recognitions import MealRecognition, Nutrition, RecognisedItem
from app.domain.constants import MealType
from app.domain.rounding import round_half_up
from app.services.auth import UserRepository
from app.services.nutrition_logs import today
from app.services.recognition import RecognitionService

router = APIRouter(prefix="/meals/recognitions", tags=["nutrition"])

User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[RecognitionService, Depends(get_recognition_service)]
RecognitionId = Annotated[str, Path(pattern="^[0-9a-f]{24}$")]
ItemIndex = Annotated[int, Path(ge=0, le=1000, description="Zero-based index in recognised_items")]
Users = Annotated[UserRepository, Depends(get_user_repository)]
FoodId = Annotated[int, Field(ge=1, le=2_147_483_647)]
Grams = Annotated[float, Field(gt=0, le=99999.9)]
Hunger = Annotated[int, Field(ge=1, le=10)]
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


# ---------------------------------------------------------------- review (B-20)


class RecognitionItemBody(BaseModel):
    food_item_id: FoodId
    grams: Grams


class RecognitionItemPatchBody(BaseModel):
    """At least one field; a field that is sent may not be null."""

    food_item_id: FoodId = Field(default=None)
    grams: Grams = Field(default=None)

    @model_validator(mode="after")
    def _some_field(self) -> "RecognitionItemPatchBody":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class ConfirmBody(BaseModel):
    log_date: date = Field(default=None, description="Defaults to today in the user's time zone")
    hunger_level_before: Hunger | None = None
    hunger_level_after: Hunger | None = None


EDIT_RESPONSES = {
    **VALIDATION_ERROR_RESPONSE,
    401: UNAUTHORIZED,
    404: {"model": Error, "description": "No pending recognition of the user, or no such item"},
}


@router.post(
    "/{recognition_id}/items",
    operation_id="addRecognitionItem",
    summary="Add a product the model missed (FR-N4)",
    responses=EDIT_RESPONSES,
)
async def add_recognition_item(
    recognition_id: RecognitionId, body: RecognitionItemBody, user: User, service: Service
) -> RecognitionOut:
    recognition = await service.add_item(user.id, recognition_id, body.food_item_id, body.grams)
    return RecognitionOut.of(recognition)


@router.patch(
    "/{recognition_id}/items/{item_index}",
    operation_id="updateRecognitionItem",
    summary="Correct a product or its grams (FR-N4)",
    responses=EDIT_RESPONSES,
)
async def update_recognition_item(
    recognition_id: RecognitionId,
    item_index: ItemIndex,
    body: RecognitionItemPatchBody,
    user: User,
    service: Service,
) -> RecognitionOut:
    recognition = await service.update_item(
        user.id, recognition_id, item_index, body.food_item_id, body.grams
    )
    return RecognitionOut.of(recognition)


@router.delete(
    "/{recognition_id}/items/{item_index}",
    operation_id="deleteRecognitionItem",
    summary="Remove a product (FR-N4)",
    responses=EDIT_RESPONSES,
)
async def delete_recognition_item(
    recognition_id: RecognitionId, item_index: ItemIndex, user: User, service: Service
) -> RecognitionOut:
    return RecognitionOut.of(await service.delete_item(user.id, recognition_id, item_index))


@router.post(
    "/{recognition_id}/confirm",
    operation_id="confirmRecognition",
    summary="Save the corrected result as a nutrition log (FR-N4)",
    status_code=201,
    responses={
        **EDIT_RESPONSES,
        409: {"model": Error, "description": "Confirmed before and that log was deleted"},
    },
)
async def confirm_recognition(
    recognition_id: RecognitionId,
    user: User,
    service: Service,
    users: Users,
    body: ConfirmBody | None = None,
) -> NutritionLogOut:
    body = body or ConfirmBody()
    now_today = today(await _timezone(users, user), datetime.now(UTC))
    log = await service.confirm(
        user.id,
        recognition_id,
        body.log_date,
        body.hunger_level_before,
        body.hunger_level_after,
        now_today,
    )
    return NutritionLogOut.of(log)
