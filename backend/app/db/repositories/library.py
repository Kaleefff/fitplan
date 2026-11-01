"""Exercise and food libraries (DB-06): filters, text search, pagination, eligibility.

Eligibility (algorithms.md 4.2, 4.3, 5.2) is filtered in SQL, so an exercise excluded
by an injury or a food with one of the user's allergens never leaves the database.
The domain functions (`app.domain.training.is_eligible`, `app.domain.diet.
food_is_eligible`) state the same rules; tests/db/test_library.py checks they agree.

Lists follow api-rules.md: ordered by name, then id, and paginated with `limit` and
`offset`; `total` counts every row that matches the filters. Names are compared
case-insensitively in byte order (`_by_name`), so the order does not depend on the
database's locale (`postgres:17` defaults to en_US.utf8, a plain cluster to C).
"""

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.enums import (
    DietRole,
    DietType,
    DifficultyLevel,
    EquipmentType,
    InjurySeverity,
    MealType,
)
from app.db.models import (
    Exercise,
    ExerciseMuscleGroup,
    FoodCategory,
    FoodItem,
    FoodItemAllergen,
    FoodItemCategory,
    Injury,
    InjuryTypeExcludedExercise,
    MuscleGroup,
    UserAllergen,
    UserExcludedFood,
)

SEVERE_INJURY = (InjurySeverity.MODERATE, InjurySeverity.SEVERE)


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class MuscleGroupRow:
    id: int
    group_name: str
    description: str
    image_url: str | None


@dataclass(frozen=True)
class ExerciseGroupRow:
    muscle_group_id: int
    group_name: str
    is_primary: bool


@dataclass(frozen=True)
class ExerciseRow:
    id: int
    name: str
    difficulty_level: DifficultyLevel
    equipment: EquipmentType
    is_compound: bool
    is_bodyweight: bool
    description: str
    instruction: str
    muscle_groups: tuple[ExerciseGroupRow, ...]  # primary first, then by name

@dataclass(frozen=True)
class FoodCategoryRow:
    id: int
    category_name: str
    description: str


@dataclass(frozen=True)
class FoodRow:
    id: int
    name: str
    cals_per_100g: Decimal
    protein_per_100g: Decimal
    fat_per_100g: Decimal
    carbs_per_100g: Decimal
    diet_role: DietRole
    suitable_meal_types: tuple[MealType, ...]
    is_vegetarian: bool
    is_vegan: bool
    default_portion_g: Decimal
    min_portion_g: Decimal
    max_portion_g: Decimal
    portion_step_g: Decimal
    category_ids: tuple[int, ...]  # ascending
    allergen_ids: tuple[int, ...]  # ascending

class SqlLibraryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    # ------------------------------------------------------------ muscle groups

    async def muscle_groups(self) -> list[MuscleGroupRow]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MuscleGroup).order_by(*_by_name(MuscleGroup.group_name, MuscleGroup.id))
            )
            return [MuscleGroupRow(g.id, g.group_name, g.description, g.image_url) for g in rows]

    # ------------------------------------------------------------ exercises

    async def list_exercises(
        self,
        *,
        q: str | None = None,
        muscle_group_id: int | None = None,
        difficulty_level: DifficultyLevel | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[ExerciseRow]:
        """`muscle_group_id` matches an exercise that trains the group, primary or not."""
        query = select(Exercise)
        if q:
            query = query.where(Exercise.name.icontains(q.strip(), autoescape=True))
        if muscle_group_id is not None:
            query = query.where(
                exists().where(
                    ExerciseMuscleGroup.exercise_id == Exercise.id,
                    ExerciseMuscleGroup.muscle_group_id == muscle_group_id,
                )
            )
        if difficulty_level is not None:
            query = query.where(Exercise.difficulty_level == difficulty_level)

        async with self._sessions() as session:
            total = await _count(session, query)
            exercises = list(
                await session.scalars(
                    query.order_by(*_by_name(Exercise.name, Exercise.id)).limit(limit)
                    .offset(offset))
            )
            groups = await _exercise_groups(session, [e.id for e in exercises])
        return Page(
            items=tuple(_exercise_row(e, groups[e.id]) for e in exercises),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_exercise(self, exercise_id: int) -> ExerciseRow | None:
        async with self._sessions() as session:
            exercise = await session.get(Exercise, exercise_id)
            if exercise is None:
                return None
            groups = await _exercise_groups(session, [exercise_id])
        return _exercise_row(exercise, groups[exercise_id])

    # ------------------------------------------------------------ foods

    async def food_categories(self) -> list[FoodCategoryRow]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(FoodCategory).order_by(
                    *_by_name(FoodCategory.category_name, FoodCategory.id)
                )
            )
            return [FoodCategoryRow(c.id, c.category_name, c.description) for c in rows]

    async def list_foods(
        self,
        *,
        q: str | None = None,
        category_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page[FoodRow]:
        """Active foods only (api-rules.md: inactive foods are hidden)."""
        query = select(FoodItem).where(FoodItem.is_active)
        if q:
            query = query.where(FoodItem.name.icontains(q.strip(), autoescape=True))
        if category_id is not None:
            query = query.where(
                exists().where(
                    FoodItemCategory.food_item_id == FoodItem.id,
                    FoodItemCategory.food_category_id == category_id,
                )
            )

        async with self._sessions() as session:
            total = await _count(session, query)
            foods = list(
                await session.scalars(
                    query.order_by(*_by_name(FoodItem.name, FoodItem.id))
                    .limit(limit)
                    .offset(offset)
                )
            )
            rows = await _food_rows(session, foods)
        return Page(items=tuple(rows), total=total, limit=limit, offset=offset)

    async def get_food(self, food_id: int) -> FoodRow | None:
        """None for an unknown or inactive food (the detail is 404 for both)."""
        async with self._sessions() as session:
            food = await session.get(FoodItem, food_id)
            if food is None or not food.is_active:
                return None
            return (await _food_rows(session, [food]))[0]

    # ------------------------------------------------------------ eligibility

    async def eligible_exercises(
        self,
        user_id: int,
        *,
        level: DifficultyLevel | None = None,
        equipment: EquipmentType | None = None,
        primary_group_id: int | None = None,
        exclude_ids: Collection[int] = (),
    ) -> list[ExerciseRow]:
        """Exercises the user may do (4.2, 4.3), compound first, then by name (4.9).

        `level` and `equipment` None mean no limit (4.9 without a profile); the user's
        active injuries always apply. `primary_group_id` and `exclude_ids` serve the
        alternatives of 4.9 (same primary group, not the current exercise and not one
        already in the session). The generator sorts by its own rule (4.6).
        """
        query = select(Exercise).where(~_excluded_by_injury(user_id))
        if level is not None:
            query = query.where(Exercise.difficulty_level <= level)  # enum order
        if equipment is not None:
            query = query.where(Exercise.equipment <= equipment)  # enum order
        if primary_group_id is not None:
            query = query.where(
                exists().where(
                    ExerciseMuscleGroup.exercise_id == Exercise.id,
                    ExerciseMuscleGroup.muscle_group_id == primary_group_id,
                    ExerciseMuscleGroup.is_primary,
                )
            )
        if exclude_ids:
            query = query.where(Exercise.id.not_in(list(exclude_ids)))

        async with self._sessions() as session:
            exercises = list(
                await session.scalars(
                    query.order_by(
                        Exercise.is_compound.desc(), *_by_name(Exercise.name, Exercise.id)
                    )
                )
            )
            groups = await _exercise_groups(session, [e.id for e in exercises])
        return [_exercise_row(e, groups[e.id]) for e in exercises]

    async def eligible_foods(
        self,
        user_id: int,
        *,
        meal_type: MealType | None = None,
        diet_type: DietType = DietType.OMNIVORE,
    ) -> list[FoodRow]:
        """Foods the user may be planned (5.2), by id (the order of 5.3).

        Active; suitable for `meal_type` (None: any meal type, for loading every slot
        at once); vegetarian or vegan when `diet_type` asks; no allergen of the user;
        not in the user's excluded foods.
        """
        query = select(FoodItem).where(
            FoodItem.is_active,
            ~exists().where(
                FoodItemAllergen.food_item_id == FoodItem.id,
                UserAllergen.allergen_id == FoodItemAllergen.allergen_id,
                UserAllergen.user_id == user_id,
            ),
            ~exists().where(
                UserExcludedFood.food_item_id == FoodItem.id,
                UserExcludedFood.user_id == user_id,
            ),
        )
        if meal_type is not None:
            query = query.where(FoodItem.suitable_meal_types.contains([meal_type]))
        if diet_type == DietType.VEGETARIAN:
            query = query.where(FoodItem.is_vegetarian)
        elif diet_type == DietType.VEGAN:
            query = query.where(FoodItem.is_vegan)

        async with self._sessions() as session:
            foods = list(await session.scalars(query.order_by(FoodItem.id)))
            return await _food_rows(session, foods)

# ---------------------------------------------------------------- helpers

def _excluded_by_injury(user_id: int) -> ColumnElement[bool]:
    """4.3: an active injury of the user excludes the exercise when (1) the injury type
    lists it, (2) its primary group is the affected group, or (3) the injury is moderate
    or severe and the affected group is one of its secondary groups.

    The inner subqueries name `exercise` two levels down, where SQLAlchemy does not
    correlate on its own, hence `correlate(Exercise, Injury)`.
    """
    listed = (
        exists()
        .where(
            InjuryTypeExcludedExercise.injury_type_id == Injury.injury_type_id,
            InjuryTypeExcludedExercise.exercise_id == Exercise.id,
        )
        .correlate(Exercise, Injury)
    )
    trains_affected_group = (
        exists()
        .where(
            ExerciseMuscleGroup.exercise_id == Exercise.id,
            ExerciseMuscleGroup.muscle_group_id == Injury.affected_muscle_group_id,
            or_(ExerciseMuscleGroup.is_primary, Injury.severity.in_(SEVERE_INJURY)),
        )
        .correlate(Exercise, Injury)
    )
    return (
        exists()
        .where(Injury.user_id == user_id, Injury.is_active, or_(listed, trains_affected_group))
        .correlate(Exercise)
    )

def _by_name(name: ColumnElement[str], id_: ColumnElement[int]) -> tuple[ColumnElement, ...]:
    """Case-insensitive name, then the exact name (capitals first), then id."""
    return func.lower(name).collate("C"), name.collate("C"), id_

async def _count(session: AsyncSession, query: Select) -> int:
    return await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))


async def _exercise_groups(
    session: AsyncSession, exercise_ids: list[int]
) -> dict[int, tuple[ExerciseGroupRow, ...]]:
    groups: dict[int, list[ExerciseGroupRow]] = defaultdict(list)
    if exercise_ids:
        rows = await session.execute(
            select(
                ExerciseMuscleGroup.exercise_id,
                MuscleGroup.id,
                MuscleGroup.group_name,
                ExerciseMuscleGroup.is_primary,
            )
            .join(MuscleGroup, MuscleGroup.id == ExerciseMuscleGroup.muscle_group_id)
            .where(ExerciseMuscleGroup.exercise_id.in_(exercise_ids))
            .order_by(
                ExerciseMuscleGroup.exercise_id,
                ExerciseMuscleGroup.is_primary.desc(),
                MuscleGroup.group_name,
            )
        )
        for exercise_id, group_id, name, is_primary in rows:
            groups[exercise_id].append(ExerciseGroupRow(group_id, name, is_primary))
    return {exercise_id: tuple(rows) for exercise_id, rows in groups.items()} | {
        exercise_id: () for exercise_id in exercise_ids if exercise_id not in groups
    }


def _exercise_row(exercise: Exercise, groups: tuple[ExerciseGroupRow, ...]) -> ExerciseRow:
    return ExerciseRow(
        id=exercise.id,
        name=exercise.name,
        difficulty_level=exercise.difficulty_level,
        equipment=exercise.equipment,
        is_compound=exercise.is_compound,
        is_bodyweight=exercise.is_bodyweight,
        description=exercise.description,
        instruction=exercise.instruction,
        muscle_groups=groups,
    )

async def _food_rows(session: AsyncSession, foods: list[FoodItem]) -> list[FoodRow]:
    ids = [f.id for f in foods]
    categories = await _links(
        session, FoodItemCategory.food_item_id, FoodItemCategory.food_category_id, ids
    )
    allergens = await _links(
        session, FoodItemAllergen.food_item_id, FoodItemAllergen.allergen_id, ids
    )
    return [
        FoodRow(
            id=f.id,
            name=f.name,
            cals_per_100g=f.cals_per_100g,
            protein_per_100g=f.protein_per_100g,
            fat_per_100g=f.fat_per_100g,
            carbs_per_100g=f.carbs_per_100g,
            diet_role=f.diet_role,
            suitable_meal_types=tuple(f.suitable_meal_types),
            is_vegetarian=f.is_vegetarian,
            is_vegan=f.is_vegan,
            default_portion_g=f.default_portion_g,
            min_portion_g=f.min_portion_g,
            max_portion_g=f.max_portion_g,
            portion_step_g=f.portion_step_g,
            category_ids=categories.get(f.id, ()),
            allergen_ids=allergens.get(f.id, ()),
        )
        for f in foods
    ]


async def _links(
    session: AsyncSession, owner: ColumnElement[int], target: ColumnElement[int], ids: list[int]
) -> dict[int, tuple[int, ...]]:
    """`owner id -> (target ids ascending)` of a link table, for the given owners."""
    links: dict[int, list[int]] = defaultdict(list)
    if ids:
        rows = await session.execute(
            select(owner, target).where(owner.in_(ids)).order_by(owner, target)
        )
        for owner_id, target_id in rows:
            links[owner_id].append(target_id)
    return {owner_id: tuple(targets) for owner_id, targets in links.items()}
