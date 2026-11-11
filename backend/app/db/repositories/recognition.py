"""Label matching and confirm of meal recognition (DB-08; FR-N2-N4; algorithms.md 11).

`ai-service` returns one `Detection` per ingredient (B-19 maps its JSON into it).
`SqlRecognitionMatcher.match` turns them into the `RecognisedItem`s of the MongoDB
buffer (DB-07); `price_item` recalculates one item after the user picks a food or
changes its grams (B-20). `RecognitionConfirmer.confirm` writes the nutrition log in
one PostgreSQL transaction, then deletes the document.

Labels are compared as `lower(trim(...))` on both sides, in SQL, so the detection and
the stored label are normalised by the same functions. Grams from the model are read
through `str`, so a float such as 12.45 is the decimal 12.45 and not 12.4499...
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import exists, func, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import String

from app.db.models import FoodItem, FoodItemAllergen, UserAllergen
from app.db.repositories.meal_recognitions import (
    Candidate,
    MongoMealRecognitionRepository,
    Nutrition,
    RecognisedItem,
)
from app.db.repositories.nutrition_logs import (
    ItemError,
    ItemIn,
    NutritionLogIn,
    NutritionLogView,
    SqlNutritionLogUnitOfWork,
    item_macros,
)
from app.domain.constants import RECOGNITION_CANDIDATES, RECOGNITION_LOW_CONFIDENCE, MealType
from app.domain.rounding import round_half_up

MAX_ITEM_GRAMS = Decimal("99999.9")  # nutrition_log_food_item.grams is NUMERIC(6, 1)
ZERO_NUTRITION = Nutrition(kcal=0.0, protein=0.0, fat=0.0, carbs=0.0)
# client_uuid of a confirmed log = uuid5(this, recognition id). Never change it: a retry
# after a failed document delete finds the log through this value.
CONFIRM_NAMESPACE = uuid.UUID("0e474fdc-f15c-4015-b794-045590db63d3")


# ---------------------------------------------------------------- errors


class FoodNotAvailableError(Exception):
    """price_item: the food does not exist or is inactive."""

    def __init__(self, food_item_id: int) -> None:
        super().__init__(food_item_id)
        self.food_item_id = food_item_id


class NoItemsError(Exception):
    """confirm: the recognition has no items (422)."""


class UnmatchedItemError(ItemError):
    """confirm: recognised_items[index] has no food_item_id yet (422)."""


# ---------------------------------------------------------------- data


@dataclass(frozen=True)
class Detection:
    """One ingredient found by the model (algorithms.md 11), as `ai-service` returns it.

    B-19 checks the JSON before mapping it: confidences finite and in 0-1. A grams
    estimate that is missing, not finite (NaN, inf) or <= 0 takes the fallback.
    """

    label: str
    confidence: float
    grams: float | None  # the model's estimate
    alternatives: tuple[tuple[str, float], ...]  # (label, confidence), extra ones ignored


@dataclass(frozen=True)
class PricedItem:
    """A picked food at the given grams; B-20 builds the RecognisedItem from it."""

    food_item_id: int
    name: str
    grams: float
    nutrition: Nutrition
    allergy_warning: bool


@dataclass
class _Group:
    """Detections of one food (or one unmatched detection) before rounding."""

    food: FoodItem | None
    grams: Decimal
    best: Detection  # highest confidence, the first on a tie
    allergens: set[int] = field(default_factory=set)


# ---------------------------------------------------------------- helpers


def _quantise(grams: Decimal) -> Decimal:
    """Half up to 0.1 g, then at most 99999.9 g.

    Clamping first gives the same result for grams >= 0 (99999.9 lies on the 0.1 grid)
    and keeps a huge estimate from overflowing the decimal context in `quantize`.
    """
    return round_half_up(min(grams, MAX_ITEM_GRAMS), 1)


def _decimal(value: float | Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _estimate(grams: float | None) -> Decimal | None:
    """The model's grams, or None when missing, not finite or <= 0 (then the fallback)."""
    estimate = _decimal(grams)
    if estimate is None or not estimate.is_finite() or estimate <= 0:
        return None
    return estimate


def _nutrition(food: FoodItem, grams: Decimal) -> Nutrition:
    macros = item_macros(food, grams)
    return Nutrition(
        kcal=float(macros.kcal),
        protein=float(macros.protein),
        fat=float(macros.fat),
        carbs=float(macros.carbs),
    )


def _candidate_labels(detection: Detection) -> tuple[tuple[str, float], ...]:
    """The label and its alternatives, K at most."""
    return ((detection.label, detection.confidence), *detection.alternatives)[
        :RECOGNITION_CANDIDATES
    ]


# ---------------------------------------------------------------- matcher


class SqlRecognitionMatcher:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def match(
        self, user_id: int, detections: Sequence[Detection]
    ) -> tuple[tuple[RecognisedItem, ...], float]:
        """The items of a new recognition and its overall confidence (algorithms.md 11).

        Items are in the order of the first detection of their food; unmatched
        detections keep their own place and are never merged.
        """
        labels = list(dict.fromkeys(label for d in detections for label, _ in _candidate_labels(d)))
        async with self._sessions() as session:
            foods, food_allergens = await _foods_by_label(session, labels)
            user_allergens = (
                set(
                    await session.scalars(
                        select(UserAllergen.allergen_id).where(UserAllergen.user_id == user_id)
                    )
                )
                if foods
                else set()
            )

        groups: list[_Group] = []
        by_food: dict[int, _Group] = {}
        for detection in detections:
            food = foods.get(detection.label)
            estimate = _estimate(detection.grams)
            if food is None:
                groups.append(_Group(None, Decimal(0) if estimate is None else estimate, detection))
                continue
            grams = food.default_portion_g if estimate is None else estimate
            group = by_food.get(food.id)
            if group is None:
                group = _Group(food, grams, detection, food_allergens.get(food.id, set()))
                by_food[food.id] = group
                groups.append(group)
            else:
                group.grams += grams
                if detection.confidence > group.best.confidence:
                    group.best = detection

        items = tuple(_item(group, foods, user_allergens) for group in groups)
        overall = max((item.confidence for item in items), default=0.0)
        return items, overall

    async def price_item(
        self, user_id: int, food_item_id: int, grams: float | Decimal
    ) -> PricedItem:
        """Grams rounded and clamped as in `match`, nutrition and allergy_warning."""
        shares_allergen = (
            exists()
            .where(
                FoodItemAllergen.food_item_id == FoodItem.id,
                UserAllergen.allergen_id == FoodItemAllergen.allergen_id,
                UserAllergen.user_id == user_id,
            )
            .correlate(FoodItem)
        )
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(FoodItem, shares_allergen).where(
                        FoodItem.id == food_item_id, FoodItem.is_active
                    )
                )
            ).first()
            if row is None:
                raise FoodNotAvailableError(food_item_id)
            food, allergy_warning = row
            quantised = _quantise(_decimal(grams))
            return PricedItem(
                food_item_id=food.id,
                name=food.name,
                grams=float(quantised),
                nutrition=_nutrition(food, quantised),
                allergy_warning=bool(allergy_warning),
            )


async def _foods_by_label(
    session: AsyncSession, labels: list[str]
) -> tuple[dict[str, FoodItem], dict[int, set[int]]]:
    """One query: the active food of each given label (as given) and the foods' allergens.

    Two active foods whose labels are equal after normalising: the lowest id wins.
    """
    foods: dict[str, FoodItem] = {}
    allergens: dict[int, set[int]] = {}
    if not labels:
        return foods, allergens
    wanted = (
        func.unnest(literal(labels, ARRAY(String)))
        .table_valued("label")
        .render_derived(name="wanted")
    )
    rows = await session.execute(
        select(wanted.c.label, FoodItem, FoodItemAllergen.allergen_id)
        .select_from(wanted)
        .join(
            FoodItem,
            func.lower(func.trim(FoodItem.recognition_label))
            == func.lower(func.trim(wanted.c.label)),
        )
        .outerjoin(FoodItemAllergen, FoodItemAllergen.food_item_id == FoodItem.id)
        .where(FoodItem.is_active)
        .order_by(FoodItem.id)
    )
    for label, food, allergen_id in rows:
        foods.setdefault(label, food)
        food_set = allergens.setdefault(food.id, set())
        if allergen_id is not None:
            food_set.add(allergen_id)
    return foods, allergens


def _item(
    group: _Group, foods: dict[str, FoodItem], user_allergens: Iterable[int]
) -> RecognisedItem:
    best = group.best
    grams = _quantise(group.grams)
    food = group.food
    return RecognisedItem(
        name=best.label,
        food_item_id=None if food is None else food.id,
        candidates=tuple(
            Candidate(
                label=label,
                confidence=float(confidence),
                food_item_id=foods[label].id if label in foods else None,
            )
            for label, confidence in _candidate_labels(best)
        ),
        confidence=float(best.confidence),
        low_confidence=best.confidence < RECOGNITION_LOW_CONFIDENCE,
        grams=float(grams),
        nutrition=ZERO_NUTRITION if food is None else _nutrition(food, grams),
        allergy_warning=food is not None and not group.allergens.isdisjoint(user_allergens),
        corrected=False,
    )


# ---------------------------------------------------------------- confirm


def confirm_client_uuid(recognition_id: str) -> uuid.UUID:
    """The client_uuid of the log confirmed from this recognition (the same on a retry)."""
    return uuid.uuid5(CONFIRM_NAMESPACE, recognition_id)


class RecognitionConfirmer:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], buffer: MongoMealRecognitionRepository
    ) -> None:
        self._logs = SqlNutritionLogUnitOfWork(sessions)
        self._buffer = buffer

    async def confirm(
        self,
        user_id: int,
        recognition_id: str,
        log_date: date,
        hunger_before: int | None,
        hunger_after: int | None,
    ) -> NutritionLogView | None:
        """The nutrition log of the recognition; None when the document is missing, expired
        or another user's.

        Raises NoItemsError, UnmatchedItemError (checked before the database), then the
        item errors of SqlNutritionLogStore.create (DuplicateFoodError, UnknownFoodError
        for a food inactive since recognition, ZeroGramsError), LogTooLargeError and
        ClientUuidDeletedError (the confirmed log was deleted before a retry); the index of
        an ItemError is the item's position in recognised_items. Nutrition is recomputed
        from food_item, not taken from the document.

        The document is deleted after the commit. If that delete fails, the error
        propagates and the log and the document both stay; a retry replays the same log
        through its client_uuid and then deletes the document.
        """
        recognition = await self._buffer.get(user_id, recognition_id)
        if recognition is None:
            return None
        items = recognition.recognised_items
        if not items:
            raise NoItemsError
        for index, item in enumerate(items):
            if item.food_item_id is None:
                raise UnmatchedItemError(index)

        log = NutritionLogIn(
            client_uuid=confirm_client_uuid(recognition.id),
            log_date=log_date,
            meal_type=MealType(recognition.meal_type.value),
            planned_meal_id=None,
            hunger_level_before=hunger_before,
            hunger_level_after=hunger_after,
            items=tuple(ItemIn(item.food_item_id, _decimal(item.grams)) for item in items),
            meal_photo_url=recognition.photo_url,
            ai_confidence=round_half_up(_decimal(recognition.overall_confidence), 2),
            ai_was_edited=any(item.corrected for item in items),
        )
        async with self._logs() as store:
            saved = await store.create(user_id, log)
        # False when the document expired or a concurrent confirm deleted it: the log stands
        await self._buffer.delete(user_id, recognition.id)
        return saved
