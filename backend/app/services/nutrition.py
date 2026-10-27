"""Energy and macro targets of the user's profile (B-10, FR-P4, FR-P5).

The profile is read through `ProfileReader`, implemented over the DB-01 `UserProfile`
model in `app/db/repositories/profiles.py`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.domain.constants import Goal, Sex
from app.domain.nutrition import NutritionTargets, calculate_targets


@dataclass(frozen=True)
class ProfileRecord:
    """The `user_profile` columns the targets need."""

    age: int
    sex: Sex
    current_weight: Decimal
    height: int
    activity_level_pal: Decimal
    goal: Goal


class ProfileReader(Protocol):
    async def get_profile(self, user_id: int) -> ProfileRecord | None: ...


async def get_nutrition_targets(
    reader: ProfileReader, user_id: int
) -> tuple[Goal, NutritionTargets]:
    profile = await reader.get_profile(user_id)
    if profile is None:
        raise AppError(404, ErrorCode.NOT_FOUND, "Profile not found")
    targets = calculate_targets(
        profile.sex,
        profile.current_weight,
        Decimal(profile.height),
        profile.age,
        profile.activity_level_pal,
        profile.goal,
    )
    return profile.goal, targets
