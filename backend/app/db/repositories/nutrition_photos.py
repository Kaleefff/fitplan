"""Photo paths of confirmed meals, for the photo cleanup job (DB-07, FR-N4).

Soft-deleted logs count too: a confirmed photo is kept until account deletion
(api-rules.md "Recognition").
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import NutritionLog


class SqlConfirmedPhotoPaths:
    """Async callable returning every `nutrition_log.meal_photo_url` of every user."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def __call__(self) -> set[str]:
        async with self._sessions() as session:
            paths = await session.scalars(
                select(NutritionLog.meal_photo_url)
                .where(NutritionLog.meal_photo_url.is_not(None))
                .distinct()
            )
            return set(paths)
