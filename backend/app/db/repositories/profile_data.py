"""Profile, injuries, allergies, excluded foods, reference lists: `ProfileStore` (B-06)."""

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import DifficultyLevel as DbLevel
from app.db.enums import EquipmentType, GoalType, SexType
from app.db.enums import InjurySeverity as DbSeverity
from app.db.models import (
    Allergen,
    FoodItem,
    FoodItemCategory,
    Injury,
    InjuryType,
    MuscleGroup,
    UserAllergen,
    UserExcludedFood,
    UserProfile,
)
from app.domain.constants import DifficultyLevel, Equipment, Goal, InjurySeverity, Sex
from app.services.profile import FoodView, InjuryIn, InjuryView, NamedView, ProfileIn, ProfileView

_ID_COLUMNS = {
    "injury_type": (InjuryType.id, None),
    "muscle_group": (MuscleGroup.id, None),
    "allergen": (Allergen.id, None),
    "active_food": (FoodItem.id, FoodItem.is_active),
}


def _injury(row: Injury) -> InjuryView:
    return InjuryView(
        id=row.id,
        injury_type_id=row.injury_type_id,
        affected_muscle_group_id=row.affected_muscle_group_id,
        severity=InjurySeverity(row.severity.value),
        start_date=row.start_date,
        is_active=row.is_active,
    )


class SqlProfileStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------ profile

    async def get_profile(self, user_id: int) -> ProfileView | None:
        row = await self._session.get(UserProfile, user_id, populate_existing=True)
        if row is None:
            return None
        return ProfileView(
            age=row.age,
            sex=Sex(row.sex.value),
            current_weight=row.current_weight,
            height=row.height,
            activity_level_pal=row.activity_level_pal,
            goal=Goal(row.goal.value),
            experience_level=DifficultyLevel(row.experience_level.value),
            equipment=Equipment(row.equipment.value),
            target_value=row.target_value,
            tdee=row.tdee,
            profile_update=row.profile_update,
        )

    async def save_profile(self, user_id: int, profile: ProfileIn, tdee_kcal: int) -> None:
        values = {
            "age": profile.age,
            "sex": SexType(profile.sex.value),
            "current_weight": profile.current_weight,
            "height": profile.height,
            "activity_level_pal": profile.activity_level_pal,
            "goal": GoalType(profile.goal.value),
            "experience_level": DbLevel(profile.experience_level.value),
            "equipment": EquipmentType(profile.equipment.value),
            "target_value": profile.target_value,
            "tdee": tdee_kcal,
            "profile_update": func.now(),
        }
        await self._session.execute(
            insert(UserProfile)
            .values(user_id=user_id, **values)
            .on_conflict_do_update(index_elements=[UserProfile.user_id], set_=values)
        )

    # ------------------------------------------------------------ injuries

    async def list_injuries(self, user_id: int) -> list[InjuryView]:
        rows = await self._session.scalars(
            select(Injury)
            .where(Injury.user_id == user_id)
            .order_by(Injury.is_active.desc(), Injury.start_date.desc(), Injury.id.desc())
        )
        return [_injury(row) for row in rows]

    async def get_injury(self, user_id: int, injury_id: int) -> InjuryView | None:
        row = await self._session.scalar(
            select(Injury)
            .where(Injury.id == injury_id, Injury.user_id == user_id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _injury(row)

    async def add_injury(self, user_id: int, injury: InjuryIn) -> int:
        row = Injury(
            user_id=user_id,
            injury_type_id=injury.injury_type_id,
            affected_muscle_group_id=injury.affected_muscle_group_id,
            severity=DbSeverity(injury.severity.value),
            start_date=injury.start_date,
            is_active=injury.is_active,
        )
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def update_injury(self, user_id: int, injury_id: int, injury: InjuryIn) -> None:
        row = await self._session.scalar(
            select(Injury).where(Injury.id == injury_id, Injury.user_id == user_id)
        )
        row.injury_type_id = injury.injury_type_id
        row.affected_muscle_group_id = injury.affected_muscle_group_id
        row.severity = DbSeverity(injury.severity.value)
        row.start_date = injury.start_date
        row.is_active = injury.is_active
        await self._session.flush()

    async def delete_injury(self, user_id: int, injury_id: int) -> bool:
        result = await self._session.execute(
            delete(Injury).where(Injury.id == injury_id, Injury.user_id == user_id)
        )
        return result.rowcount == 1

    # ------------------------------------------------------------ ids, allergies, foods

    async def known_ids(
        self, kind: Literal["injury_type", "muscle_group", "allergen", "active_food"], ids: set[int]
    ) -> set[int]:
        if not ids:
            return set()
        column, active = _ID_COLUMNS[kind]
        query = select(column).where(column.in_(ids))
        if active is not None:
            query = query.where(active)
        return set(await self._session.scalars(query))

    async def allergens(self, user_id: int | None = None) -> list[NamedView]:
        query = select(Allergen).order_by(Allergen.name, Allergen.id)
        if user_id is not None:
            query = query.join(UserAllergen, UserAllergen.allergen_id == Allergen.id).where(
                UserAllergen.user_id == user_id
            )
        return [
            NamedView(a.id, a.name, a.description, {}) for a in await self._session.scalars(query)
        ]

    async def replace_allergens(self, user_id: int, allergen_ids: list[int]) -> None:
        await self._session.execute(delete(UserAllergen).where(UserAllergen.user_id == user_id))
        self._session.add_all(UserAllergen(user_id=user_id, allergen_id=i) for i in allergen_ids)
        await self._session.flush()

    async def excluded_foods(self, user_id: int) -> list[FoodView]:
        foods = (
            await self._session.scalars(
                select(FoodItem)
                .join(UserExcludedFood, UserExcludedFood.food_item_id == FoodItem.id)
                .where(UserExcludedFood.user_id == user_id)
                .order_by(FoodItem.name, FoodItem.id)
            )
        ).all()
        categories = defaultdict(list)
        for food_id, category_id in await self._session.execute(
            select(FoodItemCategory.food_item_id, FoodItemCategory.food_category_id)
            .where(FoodItemCategory.food_item_id.in_([f.id for f in foods]))
            .order_by(FoodItemCategory.food_category_id)
        ):
            categories[food_id].append(category_id)
        return [
            FoodView(
                f.id,
                f.name,
                f.cals_per_100g,
                f.protein_per_100g,
                f.fat_per_100g,
                f.carbs_per_100g,
                tuple(categories[f.id]),
            )
            for f in foods
        ]

    async def replace_excluded_foods(self, user_id: int, food_ids: list[int]) -> None:
        await self._session.execute(
            delete(UserExcludedFood).where(UserExcludedFood.user_id == user_id)
        )
        self._session.add_all(UserExcludedFood(user_id=user_id, food_item_id=i) for i in food_ids)
        await self._session.flush()

    # ------------------------------------------------------------ reference lists

    async def injury_types(self) -> list[NamedView]:
        rows = await self._session.scalars(
            select(InjuryType).order_by(InjuryType.type_name, InjuryType.id)
        )
        return [
            NamedView(
                t.id, t.type_name, t.description, {"avg_healing_time_days": t.avg_healing_time_days}
            )
            for t in rows
        ]

    async def muscle_groups(self) -> list[NamedView]:
        rows = await self._session.scalars(
            select(MuscleGroup).order_by(MuscleGroup.group_name, MuscleGroup.id)
        )
        return [
            NamedView(g.id, g.group_name, g.description, {"image_url": g.image_url}) for g in rows
        ]


class SqlProfileUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqlProfileStore]:
        async with self._sessions.begin() as session:
            yield SqlProfileStore(session)
