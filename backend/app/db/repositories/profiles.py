"""`user_profile`: implements `app.services.nutrition.ProfileReader` (B-10)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserProfile
from app.domain.constants import Goal, Sex
from app.services.nutrition import ProfileRecord


class SqlProfileReader:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_profile(self, user_id: int) -> ProfileRecord | None:
        async with self._sessions() as session:
            profile = await session.get(UserProfile, user_id)
            if profile is None:
                return None
            return ProfileRecord(
                age=profile.age,
                sex=Sex(profile.sex.value),
                current_weight=profile.current_weight,
                height=profile.height,
                activity_level_pal=profile.activity_level_pal,
                goal=Goal(profile.goal.value),
            )
