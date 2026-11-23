"""PostgreSQL side of meal recognition for `app.services.recognition` (B-19, B-20).
Written by API, reviewed by DATA (D24).

Wraps DB-08's `SqlRecognitionMatcher` and adds the list of active recognition labels
that the backend sends to ai-service with every call (D25).
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FoodItem
from app.db.repositories.meal_recognitions import RecognisedItem
from app.db.repositories.recognition import Detection, SqlRecognitionMatcher


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
