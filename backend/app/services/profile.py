"""Profile, injuries, allergies, excluded foods and their reference lists (B-06; FR-U6, FR-U7).

api-rules.md "Profile": ranges of algorithms.md 0, one error per invalid field, TDEE
recomputed by the server, injuries listed active first then newest, allergies and
excluded foods replaced as a whole with duplicates dropped and unknown ids rejected.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from app.core.errors import AppError, ErrorCode
from app.domain.constants import DifficultyLevel, Equipment, Goal, InjurySeverity, Sex
from app.domain.nutrition import bmr, tdee


@dataclass(frozen=True)
class ProfileIn:
    age: int
    sex: Sex
    current_weight: Decimal
    height: int
    activity_level_pal: Decimal
    goal: Goal
    experience_level: DifficultyLevel
    equipment: Equipment
    target_value: Decimal | None


@dataclass(frozen=True)
class ProfileView(ProfileIn):
    tdee: int
    profile_update: datetime


@dataclass(frozen=True)
class InjuryIn:
    injury_type_id: int
    affected_muscle_group_id: int
    severity: InjurySeverity
    start_date: date
    is_active: bool


@dataclass(frozen=True)
class InjuryView(InjuryIn):
    id: int


@dataclass(frozen=True)
class NamedView:
    """A reference row: allergen, injury type, muscle group."""

    id: int
    name: str
    description: str
    extra: dict


@dataclass(frozen=True)
class FoodView:
    id: int
    name: str
    cals_per_100g: Decimal
    protein_per_100g: Decimal
    fat_per_100g: Decimal
    carbs_per_100g: Decimal
    category_ids: tuple[int, ...]


class ProfileStore(Protocol):
    """Every call of one unit of work runs in the same transaction."""

    async def get_profile(self, user_id: int) -> ProfileView | None: ...

    async def save_profile(self, user_id: int, profile: ProfileIn, tdee_kcal: int) -> None: ...

    async def list_injuries(self, user_id: int) -> list[InjuryView]: ...

    async def get_injury(self, user_id: int, injury_id: int) -> InjuryView | None: ...

    async def add_injury(self, user_id: int, injury: InjuryIn) -> int: ...

    async def update_injury(self, user_id: int, injury_id: int, injury: InjuryIn) -> None: ...

    async def delete_injury(self, user_id: int, injury_id: int) -> bool: ...

    async def known_ids(
        self, kind: Literal["injury_type", "muscle_group", "allergen", "active_food"], ids: set[int]
    ) -> set[int]:
        """The ids of `ids` that exist (for foods: exist and are active)."""
        ...

    async def allergens(self, user_id: int | None = None) -> list[NamedView]: ...

    async def replace_allergens(self, user_id: int, allergen_ids: list[int]) -> None: ...

    async def excluded_foods(self, user_id: int) -> list[FoodView]: ...

    async def replace_excluded_foods(self, user_id: int, food_ids: list[int]) -> None: ...

    async def injury_types(self) -> list[NamedView]: ...

    async def muscle_groups(self) -> list[NamedView]: ...


ProfileUnitOfWork = Callable[[], AbstractAsyncContextManager[ProfileStore]]


def _not_found(field: str, message: str) -> AppError:
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed",
        [{"field": field, "code": "not_found", "message": message}],
    )


def _today(timezone: str, now: datetime) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


class ProfileService:
    def __init__(self, unit_of_work: ProfileUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    # ------------------------------------------------------------ profile

    async def get_profile(self, user_id: int) -> ProfileView:
        async with self._unit_of_work() as store:
            profile = await store.get_profile(user_id)
        if profile is None:
            raise AppError(404, ErrorCode.NOT_FOUND, "No profile yet")
        return profile

    async def put_profile(self, user_id: int, profile: ProfileIn) -> ProfileView:
        """algorithms.md 1: TDEE from Mifflin-St Jeor and the PAL, recomputed on every save."""
        energy = tdee(
            bmr(profile.sex, profile.current_weight, Decimal(profile.height), profile.age),
            profile.activity_level_pal,
        )
        async with self._unit_of_work() as store:
            await store.save_profile(user_id, profile, energy)
            return await store.get_profile(user_id)

    # ------------------------------------------------------------ injuries

    async def list_injuries(self, user_id: int) -> list[InjuryView]:
        async with self._unit_of_work() as store:
            return await store.list_injuries(user_id)

    async def _check_injury(
        self, store: ProfileStore, injury: InjuryIn, timezone: str, now: datetime
    ) -> None:
        if injury.start_date > _today(timezone, now):
            raise AppError(
                422,
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                [
                    {
                        "field": "body.start_date",
                        "code": "future_date",
                        "message": "Start date is in the future",
                    }
                ],
            )
        if not await store.known_ids("injury_type", {injury.injury_type_id}):
            raise _not_found("body.injury_type_id", "Unknown injury type")
        if not await store.known_ids("muscle_group", {injury.affected_muscle_group_id}):
            raise _not_found("body.affected_muscle_group_id", "Unknown muscle group")

    async def add_injury(
        self, user_id: int, injury: InjuryIn, timezone: str, now: datetime
    ) -> InjuryView:
        async with self._unit_of_work() as store:
            await self._check_injury(store, injury, timezone, now)
            injury_id = await store.add_injury(user_id, injury)
            return await store.get_injury(user_id, injury_id)

    async def update_injury(
        self, user_id: int, injury_id: int, changes: dict, timezone: str, now: datetime
    ) -> InjuryView:
        async with self._unit_of_work() as store:
            current = await store.get_injury(user_id, injury_id)
            if current is None:
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")
            updated = InjuryIn(
                **{
                    name: getattr(replace(current, **changes), name)
                    for name in InjuryIn.__dataclass_fields__
                }
            )
            await self._check_injury(store, updated, timezone, now)
            await store.update_injury(user_id, injury_id, updated)
            return await store.get_injury(user_id, injury_id)

    async def delete_injury(self, user_id: int, injury_id: int) -> None:
        async with self._unit_of_work() as store:
            if not await store.delete_injury(user_id, injury_id):
                raise AppError(404, ErrorCode.NOT_FOUND, "Not found")

    # ------------------------------------------------------------ allergies, excluded foods

    async def get_allergens(self, user_id: int) -> list[NamedView]:
        async with self._unit_of_work() as store:
            return await store.allergens(user_id)

    async def put_allergens(self, user_id: int, allergen_ids: list[int]) -> list[NamedView]:
        """Replaced as a whole; duplicates dropped; an unknown id changes nothing."""
        wanted = list(dict.fromkeys(allergen_ids))
        async with self._unit_of_work() as store:
            known = await store.known_ids("allergen", set(wanted))
            if missing := [i for i in wanted if i not in known]:
                raise _not_found("body.allergen_ids", f"Unknown allergen ids {missing}")
            await store.replace_allergens(user_id, wanted)
            return await store.allergens(user_id)

    async def get_excluded_foods(self, user_id: int) -> list[FoodView]:
        async with self._unit_of_work() as store:
            return await store.excluded_foods(user_id)

    async def put_excluded_foods(self, user_id: int, food_ids: list[int]) -> list[FoodView]:
        """As allergies; an inactive food counts as unknown (api-rules.md Conventions)."""
        wanted = list(dict.fromkeys(food_ids))
        async with self._unit_of_work() as store:
            known = await store.known_ids("active_food", set(wanted))
            if missing := [i for i in wanted if i not in known]:
                raise _not_found("body.food_item_ids", f"Unknown or inactive food ids {missing}")
            await store.replace_excluded_foods(user_id, wanted)
            return await store.excluded_foods(user_id)

    # ------------------------------------------------------------ reference lists

    async def reference(self, kind: str) -> list[NamedView]:
        async with self._unit_of_work() as store:
            if kind == "allergens":
                return await store.allergens()
            if kind == "injury_types":
                return await store.injury_types()
            return await store.muscle_groups()
