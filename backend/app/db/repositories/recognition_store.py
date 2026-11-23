"""PostgreSQL side of meal recognition for `app.services.recognition` (B-19, B-20).
Written by API, reviewed by DATA (D24).

Wraps DB-08's `SqlRecognitionMatcher` and `RecognitionConfirmer` and adds the list of
active recognition labels that the backend sends to ai-service with every call (D25).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FoodItem
from app.db.repositories.meal_recognitions import MongoMealRecognitionRepository, RecognisedItem
from app.db.repositories.nutrition_logs import NutritionLogView
from app.db.repositories.recognition import (
    Detection,
    PricedItem,
    RecognitionConfirmer,
    SqlRecognitionMatcher,
)


class SqlRecognitionStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._matcher = SqlRecognitionMatcher(sessions)

    async def active_labels(self) -> list[str]:
        """`recognition_label` of every active food, as stored (unique, A-01)."""
        async with self._sessions() as session:
            labels = await session.scalars(
                select(FoodItem.recognition_label)
                .where(FoodItem.is_active, FoodItem.recognition_label.is_not(None))
                .order_by(FoodItem.recognition_label)
            )
            return list(labels)

    async def match(
        self, user_id: int, detections: Sequence[Detection]
    ) -> tuple[tuple[RecognisedItem, ...], float]:
        return await self._matcher.match(user_id, detections)

    async def price_item(
        self, user_id: int, food_item_id: int, grams: float | Decimal
    ) -> PricedItem:
        """Raises FoodNotAvailableError for an unknown or inactive food."""
        return await self._matcher.price_item(user_id, food_item_id, grams)

    async def confirm(
        self,
        buffer: MongoMealRecognitionRepository,
        user_id: int,
        recognition_id: str,
        log_date: date,
        hunger_before: int | None,
        hunger_after: int | None,
    ) -> NutritionLogView | None:
        """DB-08's confirm: the nutrition log in one transaction, then the document is
        deleted; None for a missing, expired or another user's recognition."""
        confirmer = RecognitionConfirmer(self._sessions, buffer)
        return await confirmer.confirm(
            user_id, recognition_id, log_date, hunger_before, hunger_after
        )
