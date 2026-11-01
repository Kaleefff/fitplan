"""Exercise and food libraries on PostgreSQL with the reference seed (DB-06).

The seed is loaded once per module (every test here only reads); skipped without
PostgreSQL.
"""

import itertools
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.enums import DietType, DifficultyLevel, EquipmentType, MealType
from app.db.repositories.library import SqlLibraryRepository
from app.db.repositories.training_plans import SqlTrainingPlanStore
from app.db.seed import load
from app.db.session import database_url
from app.domain import constants as domain
from app.domain.diet import FoodInfo, food_is_eligible
from app.domain.training import is_eligible
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio
INACTIVE = "Smoked salmon"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def seeded(migrated_db) -> None:  # noqa: F811
    engine = create_engine(database_url().set(database=TEST_DB))
    with engine.begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, exercise, exercise_muscle_group, injury_type,"
                " food_item, food_category, allergen RESTART IDENTITY CASCADE"
            )
        )
        load(db)
        db.execute(
            text("UPDATE food_item SET is_active = false WHERE name = :name"), {"name": INACTIVE}
        )
    engine.dispose()


@pytest.fixture
async def library(seeded) -> AsyncIterator[SqlLibraryRepository]:
    engine = create_async_engine(database_url().set(database=TEST_DB))
    yield SqlLibraryRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()

@pytest.fixture
def users(seeded) -> Iterator["Users"]:
    """Users with injuries, allergies and excluded foods; removed after the test."""
    engine = create_engine(database_url().set(database=TEST_DB))
    yield Users(engine)
    with engine.begin() as db:
        db.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
    engine.dispose()


class Users:
    def __init__(self, engine) -> None:
        self._engine = engine

    def _run(self, sql: str, **params):
        with self._engine.begin() as db:
            return db.execute(text(sql), params)

    def id_of(self, table: str, column: str, value: str) -> int:
        return self._run(f"SELECT id FROM {table} WHERE {column} = :v", v=value).scalar_one()

    def create(self, email: str = "ann@example.com") -> int:
        return self._run(
            "INSERT INTO app_user (email, name, surname) VALUES (:e, 'A', 'B') RETURNING id",
            e=email,
        ).scalar_one()

    def injure(
        self, user_id: int, injury_type: str, group: str, severity: str, active: bool = True
    ) -> None:
        self._run(
            "INSERT INTO injury (user_id, injury_type_id, affected_muscle_group_id, severity,"
            " start_date, is_active) VALUES (:u, :t, :g, CAST(:s AS injury_severity),"
            " CURRENT_DATE, :a)",
            u=user_id,
            t=self.id_of("injury_type", "type_name", injury_type),
            g=self.id_of("muscle_group", "group_name", group),
            s=severity,
            a=active,
        )

    def allergic_to(self, user_id: int, allergen: str) -> int:
        allergen_id = self.id_of("allergen", "name", allergen)
        self._run("INSERT INTO user_allergen VALUES (:u, :a)", u=user_id, a=allergen_id)
        return allergen_id

    def exclude_food(self, user_id: int, food: str) -> int:
        food_id = self.id_of("food_item", "name", food)
        self._run(
            "INSERT INTO user_excluded_food (user_id, food_item_id) VALUES (:u, :f)",
            u=user_id,
            f=food_id,
        )
        return food_id

    def excluded_exercises(self, injury_type: str) -> set[int]:
        return set(
            self._run(
                "SELECT x.exercise_id FROM injury_type_excluded_exercise x"
                " JOIN injury_type t ON t.id = x.injury_type_id WHERE t.type_name = :t",
                t=injury_type,
            ).scalars()
        )

    def food_infos(self) -> list[FoodInfo]:
        """Every food, inactive included, with what 5.2 reads (the rest is filler)."""
        rows = self._run(
            "SELECT f.id, f.is_active, f.suitable_meal_types::text[], f.is_vegetarian,"
            " f.is_vegan, coalesce(array_agg(a.allergen_id)"
            " FILTER (WHERE a.allergen_id IS NOT NULL), '{}')"
            " FROM food_item f LEFT JOIN food_item_allergen a ON a.food_item_id = f.id"
            " GROUP BY f.id ORDER BY f.id"
        )
        return [
            FoodInfo(
                id=food_id,
                diet_role=domain.DietRole.OTHER,
                suitable_meal_types=frozenset(domain.MealType(m) for m in meal_types),
                per_100g=(0.0, 0.0, 0.0, 0.0),
                min_portion_g=10,
                max_portion_g=10,
                portion_step_g=10,
                is_active=is_active,
                is_vegetarian=vegetarian,
                is_vegan=vegan,
                allergen_ids=frozenset(allergens),
            )
            for food_id, is_active, meal_types, vegetarian, vegan, allergens in rows
        ]

def _by_name(name: str, id_: int) -> tuple:
    """The repository's order: case-insensitive name, then the exact name, then id."""
    return name.lower(), name, id_

async def _all(list_page, **filters):
    page = await list_page(limit=100, **filters)
    items = list(page.items)
    while len(items) < page.total:
        page = await list_page(limit=100, offset=len(items), **filters)
        items += page.items
    return items


async def _all_exercises(library: SqlLibraryRepository, **filters):
    return await _all(library.list_exercises, **filters)


async def _all_foods(library: SqlLibraryRepository, **filters):
    return await _all(library.list_foods, **filters)


# ---------------------------------------------------------------- muscle groups


async def test_muscle_groups_are_ordered_by_name(library):
    groups = await library.muscle_groups()
    assert groups
    assert groups == sorted(groups, key=lambda g: _by_name(g.group_name, g.id))


# ---------------------------------------------------------------- exercises


async def test_exercises_are_ordered_by_name_then_id_and_paginated(library):
    first = await library.list_exercises(limit=10)
    second = await library.list_exercises(limit=10, offset=10)
    everything = await _all_exercises(library)

    assert first.total == second.total == len(everything)
    assert (first.limit, first.offset, second.offset) == (10, 0, 10)
    assert len(first.items) == 10
    assert [e.id for e in first.items + second.items] == [e.id for e in everything[:20]]
    assert everything == sorted(everything, key=lambda e: _by_name(e.name, e.id))

async def test_offset_past_the_end_is_an_empty_page_with_the_total(library):
    page = await library.list_exercises(offset=10_000)
    assert page.items == ()
    assert page.total > 0


async def test_search_is_case_insensitive_and_treats_wildcards_literally(library):
    everything = await _all_exercises(library)
    word = everything[0].name.split()[0]

    found = await _all_exercises(library, q=word.swapcase())
    assert found
    assert all(word.lower() in e.name.lower() for e in found)
    assert (await library.list_exercises(q="%")).total == 0
    assert (await library.list_exercises(q="_")).total == 0


async def test_muscle_group_filter_matches_primary_and_secondary_groups(library):
    groups = {g.group_name: g.id for g in await library.muscle_groups()}
    chest = groups["chest"]
    found = await _all_exercises(library, muscle_group_id=chest)

    assert found
    assert all(any(g.muscle_group_id == chest for g in e.muscle_groups) for e in found)
    triceps = groups["triceps"]
    assert any(
        not next(g for g in e.muscle_groups if g.muscle_group_id == triceps).is_primary
        for e in await _all_exercises(library, muscle_group_id=triceps)
    )


async def test_difficulty_filter(library):
    found = await _all_exercises(library, difficulty_level=DifficultyLevel.ADVANCED)
    assert found
    assert {e.difficulty_level for e in found} == {DifficultyLevel.ADVANCED}


async def test_filters_combine(library):
    groups = {g.group_name: g.id for g in await library.muscle_groups()}
    found = await _all_exercises(
        library, muscle_group_id=groups["back"], difficulty_level=DifficultyLevel.BEGINNER
    )
    assert all(e.difficulty_level == DifficultyLevel.BEGINNER for e in found)
    assert all(any(g.group_name == "back" for g in e.muscle_groups) for e in found)


async def test_exercise_detail_lists_the_primary_group_first(library):
    some = (await library.list_exercises(limit=1)).items[0]
    exercise = await library.get_exercise(some.id)

    assert exercise == some
    assert exercise.muscle_groups[0].is_primary
    assert sum(g.is_primary for g in exercise.muscle_groups) == 1

async def test_unknown_exercise_is_none(library):
    assert await library.get_exercise(999_999) is None


# ---------------------------------------------------------------- foods


async def test_food_categories_are_ordered_by_name(library):
    categories = await library.food_categories()
    assert categories
    assert categories == sorted(categories, key=lambda c: _by_name(c.category_name, c.id))


async def test_foods_are_ordered_by_name_then_id_and_paginated(library):
    first = await library.list_foods(limit=10)
    second = await library.list_foods(limit=10, offset=10)
    everything = await _all_foods(library)

    assert first.total == second.total == len(everything)
    assert [f.id for f in first.items + second.items] == [f.id for f in everything[:20]]
    assert everything == sorted(everything, key=lambda f: _by_name(f.name, f.id))


async def test_inactive_food_is_hidden_from_list_search_and_detail(library):
    everything = await _all_foods(library)
    hidden = _food_id(INACTIVE)

    assert hidden not in {f.id for f in everything}
    assert all(f.name != INACTIVE for f in await _all_foods(library, q="salmon"))
    assert await library.get_food(hidden) is None


async def test_food_search_is_case_insensitive_and_treats_wildcards_literally(library):
    salmon = await _all_foods(library, q="SALMON")
    assert salmon
    assert all("salmon" in f.name.lower() for f in salmon)

    percent = await _all_foods(library, q="%")
    assert percent
    assert all("%" in f.name for f in percent)
    assert len(percent) < len(await _all_foods(library))


async def test_category_filter(library):
    fruits = next(c.id for c in await library.food_categories() if c.category_name == "Fruits")
    found = await _all_foods(library, category_id=fruits)

    assert found
    assert all(fruits in f.category_ids for f in found)
    assert (await library.list_foods(category_id=999_999)).total == 0


async def test_food_detail_carries_categories_and_allergens(library):
    nuggets = (await library.list_foods(q="Chicken nuggets")).items[0]
    food = await library.get_food(nuggets.id)

    assert food == nuggets
    assert food.category_ids
    assert food.allergen_ids
    assert list(food.allergen_ids) == sorted(food.allergen_ids)
    assert food.suitable_meal_types


async def test_unknown_food_is_none(library):
    assert await library.get_food(999_999) is None


def _food_id(name: str) -> int:
    engine = create_engine(database_url().set(database=TEST_DB))
    with engine.connect() as db:
        food_id = db.execute(
            text("SELECT id FROM food_item WHERE name = :name"), {"name": name}
        ).scalar_one()
    engine.dispose()
    return food_id

# ---------------------------------------------------------------- exercise eligibility

SHOULDER = "Shoulder strain"


def _ids(rows) -> set[int]:
    return {r.id for r in rows}


async def test_without_injuries_or_limits_every_exercise_is_eligible(library, users):
    user = users.create()
    assert _ids(await library.eligible_exercises(user)) == _ids(await _all_exercises(library))


async def test_level_and_equipment_are_upper_limits(library, users):
    user = users.create()
    found = await library.eligible_exercises(
        user, level=DifficultyLevel.INTERMEDIATE, equipment=EquipmentType.HOME
    )
    everything = await _all_exercises(library)

    assert found
    assert all(e.difficulty_level != DifficultyLevel.ADVANCED for e in found)
    assert all(e.equipment != EquipmentType.GYM for e in found)
    assert len(found) < len(everything)


async def test_injury_type_exclusions_are_never_returned(library, users):
    user = users.create()
    users.injure(user, SHOULDER, "calves", "mild")  # the group excludes nothing relevant
    excluded = users.excluded_exercises(SHOULDER)

    assert excluded
    assert not excluded & _ids(await library.eligible_exercises(user))


async def test_mild_injury_excludes_the_primary_group_only(library, users):
    user = users.create()
    users.injure(user, SHOULDER, "triceps", "mild")
    found = await library.eligible_exercises(user)

    assert not any(_primary(e) == "triceps" for e in found)
    assert any("triceps" in _secondary(e) for e in found)


async def test_moderate_or_severe_injury_also_excludes_secondary_groups(library, users):
    for severity in ("moderate", "severe"):
        user = users.create(f"{severity}@example.com")
        users.injure(user, SHOULDER, "triceps", severity)
        found = await library.eligible_exercises(user)

        assert found
        assert not any(_primary(e) == "triceps" or "triceps" in _secondary(e) for e in found), (
            severity
        )


async def test_inactive_injuries_and_other_users_injuries_do_not_count(library, users):
    user, other = users.create(), users.create("bob@example.com")
    users.injure(user, SHOULDER, "chest", "severe", active=False)
    users.injure(other, SHOULDER, "chest", "severe")

    assert _ids(await library.eligible_exercises(user)) == _ids(await _all_exercises(library))
    assert len(await library.eligible_exercises(other)) < len(await _all_exercises(library))


async def test_alternatives_keep_the_primary_group_and_skip_the_session(library, users):
    user = users.create()
    groups = {g.group_name: g.id for g in await library.muscle_groups()}
    chest = await library.eligible_exercises(user, primary_group_id=groups["chest"])
    current, in_session = chest[0].id, chest[1].id

    found = await library.eligible_exercises(
        user, primary_group_id=groups["chest"], exclude_ids={current, in_session}
    )

    assert _ids(found) == _ids(chest) - {current, in_session}
    assert all(_primary(e) == "chest" for e in found)
    assert found == sorted(found, key=lambda e: (not e.is_compound, *_by_name(e.name, e.id)))


async def test_exercise_eligibility_agrees_with_the_domain_rule(library, users):
    user = users.create()
    users.injure(user, SHOULDER, "chest", "mild")
    users.injure(user, "Rotator cuff tendinopathy", "back", "moderate")
    engine = create_async_engine(database_url().set(database=TEST_DB))
    async with async_sessionmaker(engine)() as session:
        store = SqlTrainingPlanStore(session)
        catalogue, injuries = await store.catalogue(), await store.active_injuries(user)
    await engine.dispose()
    assert len(injuries) == 2

    for level, equipment in itertools.product(DifficultyLevel, EquipmentType):
        expected = {
            e.id
            for e in catalogue
            if is_eligible(e, domain.DifficultyLevel(level), domain.Equipment(equipment), injuries)
        }
        found = await library.eligible_exercises(user, level=level, equipment=equipment)
        assert _ids(found) == expected, (level, equipment)


def _primary(exercise) -> str:
    return next(g.group_name for g in exercise.muscle_groups if g.is_primary)


def _secondary(exercise) -> set[str]:
    return {g.group_name for g in exercise.muscle_groups if not g.is_primary}


# ---------------------------------------------------------------- food eligibility


async def test_food_with_an_allergen_of_the_user_is_never_returned(library, users):
    user = users.create()
    fish = users.allergic_to(user, "Fish")
    gluten = users.allergic_to(user, "Gluten")
    everything = await _all_foods(library)

    for meal_type in (None, *MealType):
        found = await library.eligible_foods(user, meal_type=meal_type)
        assert found
        assert not any({fish, gluten} & set(f.allergen_ids) for f in found), meal_type
    assert any(fish in f.allergen_ids for f in everything)
    assert any(gluten in f.allergen_ids for f in everything)


async def test_excluded_and_inactive_foods_are_never_returned(library, users):
    user = users.create()
    excluded = users.exclude_food(user, "Chicken nuggets")
    found = _ids(await library.eligible_foods(user))

    assert excluded not in found
    assert _food_id(INACTIVE) not in found


async def test_meal_type_and_diet_type_filters(library, users):
    user = users.create()
    snacks = await library.eligible_foods(user, meal_type=MealType.SNACK)
    vegetarian = await library.eligible_foods(user, diet_type=DietType.VEGETARIAN)
    vegan = await library.eligible_foods(user, diet_type=DietType.VEGAN)

    assert all(MealType.SNACK in f.suitable_meal_types for f in snacks)
    assert vegetarian and all(f.is_vegetarian for f in vegetarian)
    assert vegan and all(f.is_vegan for f in vegan)
    assert len(vegan) < len(vegetarian) < len(await library.eligible_foods(user))
    assert [f.id for f in snacks] == sorted(f.id for f in snacks)


async def test_other_users_restrictions_do_not_count(library, users):
    user, other = users.create(), users.create("bob@example.com")
    users.allergic_to(other, "Fish")
    users.exclude_food(other, "Chicken nuggets")

    assert len(await library.eligible_foods(user)) > len(await library.eligible_foods(other))
    assert len(await library.eligible_foods(user)) == len(await _all_foods(library))


async def test_food_eligibility_agrees_with_the_domain_rule(library, users):
    user = users.create()
    allergens = frozenset({users.allergic_to(user, "Milk"), users.allergic_to(user, "Peanuts")})
    excluded = frozenset({users.exclude_food(user, "Chicken nuggets")})
    foods = users.food_infos()

    for meal_type, diet_type in itertools.product(MealType, DietType):
        expected = {
            f.id
            for f in foods
            if food_is_eligible(
                f, domain.MealType(meal_type), domain.DietType(diet_type), allergens, excluded
            )
        }
        found = await library.eligible_foods(user, meal_type=meal_type, diet_type=diet_type)
        assert _ids(found) == expected, (meal_type, diet_type)
