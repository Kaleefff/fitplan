"""Custom exercises on PostgreSQL (DB-16, FR-P10, D26).

Isolation: another user's custom exercise is invisible in every exercise read and cannot
be referenced by any write. Owner scope: only the owner changes or deletes a custom
exercise; library exercises are read-only. Names are unique per user; a custom exercise
has exactly one primary group; an exercise in use is not deleted; deleting a user
removes their custom exercises. Skipped without PostgreSQL.
"""

import asyncio
import functools
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.enums import DifficultyLevel as DbLevel
from app.db.enums import EquipmentType
from app.db.repositories import custom_exercises
from app.db.repositories.custom_exercises import (
    EXERCISE_REFERENCES,
    CustomExerciseIn,
    MuscleGroupsIn,
    SqlCustomExerciseRepository,
    WriteError,
)
from app.db.repositories.library import ExerciseRow, SqlLibraryRepository
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.seed import load
from app.db.session import database_url
from app.domain.constants import DifficultyLevel, Equipment, Goal
from app.domain.training import GeneratedPlan, PlanExercise, PlanSession
from app.services.training_plans import PlanRequest
from app.services.workouts import ExerciseIn, SetIn, WorkoutIn
from tests.clock import today
from tests.db.conftest import delete_users
from tests.db.test_library import _by_name
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio

TODAY = today()
EVERYTHING = 1000  # a page larger than the seeded library plus a test's exercises


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB), pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


@pytest.fixture(scope="module")
def seeded(migrated_db):  # noqa: F811
    with _sync_engine().begin() as db:
        delete_users(db)
        db.execute(
            text(
                "TRUNCATE muscle_group, exercise, exercise_muscle_group, injury_type, allergen,"
                " food_category, food_item RESTART IDENTITY CASCADE"
            )
        )
        load(db)


@dataclass
class Repos:
    sessions: async_sessionmaker
    library: SqlLibraryRepository
    custom: SqlCustomExerciseRepository
    plans: SqlTrainingPlanUnitOfWork
    workouts: SqlWorkoutUnitOfWork


@pytest.fixture
async def repos(seeded):
    """Every test starts without users, so without custom exercises; the library stays."""
    with _sync_engine().begin() as db:
        delete_users(db)
    engine = create_async_engine(database_url().set(database=TEST_DB))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield Repos(
        sessions,
        SqlLibraryRepository(sessions),
        SqlCustomExerciseRepository(sessions),
        SqlTrainingPlanUnitOfWork(sessions),
        SqlWorkoutUnitOfWork(sessions),
    )
    await engine.dispose()


# ---------------------------------------------------------------- helpers


def _sql(sql: str, **params):
    with _sync_engine().begin() as db:
        return db.execute(text(sql), params)


def _user(email: str) -> int:
    return _sql(
        "INSERT INTO app_user (email, password_hash, name, surname)"
        " VALUES (:e, 'x', 'A', 'B') RETURNING id",
        e=email,
    ).scalar_one()


def _group(name: str) -> int:
    return _sql("SELECT id FROM muscle_group WHERE group_name = :n", n=name).scalar_one()


def _library_exercise(primary: str = "chest", skip: int = 0) -> int:
    return _sql(
        "SELECT e.id FROM exercise e JOIN exercise_muscle_group l ON l.exercise_id = e.id"
        " JOIN muscle_group m ON m.id = l.muscle_group_id"
        " WHERE e.user_id IS NULL AND l.is_primary AND m.group_name = :g"
        " ORDER BY e.id OFFSET :s LIMIT 1",
        g=primary,
        s=skip,
    ).scalar_one()


def _plan(user_id: int, exercise_id: int) -> int:
    """An archived one-session plan holding `exercise_id`; returns the session exercise id.
    Archived, so a user may have several (the repositories do not look at the status)."""
    plan_id = _sql(
        "INSERT INTO training_plan (user_id, plan_name, goal, num_training_days,"
        " experience_level, equipment, status, start_date, end_date)"
        " VALUES (:u, 'Plan', 'strength', 1, 'advanced', 'gym', 'archived', :d, :d)"
        " RETURNING id",
        u=user_id,
        d=TODAY,
    ).scalar_one()
    session_id = _sql(
        "INSERT INTO training_session (training_plan_id, session_order, session_name,"
        " day_of_week, estimated_duration) VALUES (:p, 1, 'Full Body', 1, 60) RETURNING id",
        p=plan_id,
    ).scalar_one()
    return _sql(
        "INSERT INTO session_exercise (training_session_id, exercise_id, sort_order,"
        " planned_sets, planned_reps, rest_seconds) VALUES (:s, :e, 1, 3, 10, 60) RETURNING id",
        s=session_id,
        e=exercise_id,
    ).scalar_one()


def _references(exercise_id: int) -> int:
    """Rows of the four tables whose foreign keys point at the exercise (D26)."""
    return _sql(
        "SELECT (SELECT count(*) FROM session_exercise"
        "        WHERE :e IN (exercise_id, original_exercise_id))"
        " + (SELECT count(*) FROM workout_log_exercise WHERE exercise_id = :e)"
        " + (SELECT count(*) FROM personal_record WHERE exercise_id = :e)",
        e=exercise_id,
    ).scalar_one()


def _exercise_state(exercise_id: int) -> tuple:
    row = _sql("SELECT * FROM exercise WHERE id = :e", e=exercise_id).one_or_none()
    groups = _sql(
        "SELECT muscle_group_id, is_primary FROM exercise_muscle_group"
        " WHERE exercise_id = :e ORDER BY 1",
        e=exercise_id,
    ).all()
    return None if row is None else tuple(row), tuple(tuple(g) for g in groups)


def _new(name: str, primary: str = "chest", secondary: tuple[str, ...] = ("triceps",)):
    return CustomExerciseIn(
        name=name,
        difficulty_level=DbLevel.BEGINNER,
        equipment=EquipmentType.NONE,
        is_compound=True,
        is_bodyweight=True,
        muscle_groups=MuscleGroupsIn(_group(primary), tuple(_group(g) for g in secondary)),
    )


async def _create(repos: Repos, user_id: int, name: str, **kwargs) -> ExerciseRow:
    created = await repos.custom.create(user_id, _new(name, **kwargs))
    assert isinstance(created, ExerciseRow), created
    return created


def _ids(rows) -> set[int]:
    return {r.id for r in rows}


def _workout(exercise_id: int) -> WorkoutIn:
    sets = (SetIn(1, 10, Decimal("60"), True, None),)
    return WorkoutIn(None, None, TODAY, 7, (ExerciseIn(exercise_id, None, 1, sets),))


# ---------------------------------------------------------------- reads (isolation)


async def test_another_users_custom_exercise_is_invisible_in_every_read(repos):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    mine = await _create(repos, ann, "Zercher floor press")
    chest = _group("chest")
    lib = repos.library

    for user, sees in ((ann, True), (bob, False)):
        everything = await lib.list_exercises(user, custom_only=False, limit=EVERYTHING)
        searched = await lib.list_exercises(user, custom_only=False, q="zercher")
        own = await lib.list_exercises(user, custom_only=True, limit=EVERYTHING)
        alternatives = await lib.eligible_exercises(user, primary_group_id=chest)
        async with repos.plans() as store:
            catalogue = await store.catalogue(user, include_custom=True)
        async with repos.workouts() as store:
            names = await store.exercise_names(user, {mine.id})
        found = {
            "list": mine.id in _ids(everything.items),
            "search": mine.id in _ids(searched.items),
            "custom_only": mine.id in _ids(own.items),
            "detail": await lib.get_exercise(user, mine.id) is not None,
            "eligibility": mine.id in _ids(await lib.eligible_exercises(user)),
            "alternatives": mine.id in _ids(alternatives),
            "catalogue": mine.id in {e.id for e in catalogue},
            "exercise_names": mine.id in names,
        }
        assert found == dict.fromkeys(found, sees), user

    async with repos.plans() as store:  # the generator's catalogue (questions.md)
        assert mine.id not in {e.id for e in await store.catalogue(ann, include_custom=False)}


async def test_custom_only_returns_own_rows_paginated_and_searchable(repos):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    alpha = await _create(repos, ann, "alpha curl", primary="biceps", secondary=())
    beta = await _create(repos, ann, "Beta curl", primary="biceps", secondary=())
    gamma = await _create(repos, ann, "Gamma press")
    await _create(repos, bob, "Bob curl", primary="biceps", secondary=())
    lib = repos.library

    first = await lib.list_exercises(ann, custom_only=True, limit=2)
    second = await lib.list_exercises(ann, custom_only=True, limit=2, offset=2)
    assert (first.total, second.total) == (3, 3)
    assert [e.id for e in first.items + second.items] == [alpha.id, beta.id, gamma.id]
    curls = await lib.list_exercises(ann, custom_only=True, q="CURL")
    assert [e.id for e in curls.items] == [alpha.id, beta.id]

    library = await lib.list_exercises(0, custom_only=False, limit=EVERYTHING)
    mixed = await lib.list_exercises(ann, custom_only=False, limit=EVERYTHING)
    assert mixed.total == library.total + 3
    assert _ids(mixed.items) == _ids(library.items) | {alpha.id, beta.id, gamma.id}
    assert list(mixed.items) == sorted(mixed.items, key=lambda e: _by_name(e.name, e.id))


async def test_is_custom_marks_own_rows_in_list_detail_and_alternatives(repos):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press")
    lib = repos.library

    listed = (await lib.list_exercises(ann, custom_only=False, limit=EVERYTHING)).items
    assert {e.id for e in listed if e.is_custom} == {mine.id}
    assert (await lib.get_exercise(ann, mine.id)).is_custom
    assert not (await lib.get_exercise(ann, _library_exercise())).is_custom
    alternatives = await lib.eligible_exercises(ann, primary_group_id=_group("chest"))
    assert {e.id for e in alternatives if e.is_custom} == {mine.id}


# ---------------------------------------------------------------- create and update


async def test_create_stores_one_primary_group_and_empty_texts(repos):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press", secondary=("triceps", "shoulders"))

    assert mine.is_custom
    assert (mine.description, mine.instruction) == ("", "")  # custom-exercise-text
    assert [g.is_primary for g in mine.muscle_groups] == [True, False, False]
    assert mine.muscle_groups[0].muscle_group_id == _group("chest")
    assert await repos.library.get_exercise(ann, mine.id) == mine


async def test_names_are_unique_per_user_case_insensitively(repos):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    library_name = _sql(
        "SELECT name FROM exercise WHERE id = :e", e=_library_exercise()
    ).scalar_one()

    mine = await _create(repos, ann, library_name)  # a library name is allowed
    await _create(repos, bob, library_name)  # so is another user's name
    assert await repos.custom.create(ann, _new(library_name.upper())) == WriteError.NAME_TAKEN
    other = await _create(repos, ann, "Other press")
    renamed = await repos.custom.update(ann, other.id, {"name": library_name.lower()})
    assert renamed == WriteError.NAME_TAKEN
    unchanged = _sql("SELECT name FROM exercise WHERE id = :e", e=other.id).scalar_one()
    assert unchanged == "Other press"
    assert (await repos.custom.update(ann, mine.id, {"name": library_name})).id == mine.id


@pytest.mark.parametrize(
    ("primary", "secondary"),
    [
        ("chest", ("chest",)),  # the primary among the secondary groups
        ("chest", ("triceps", "triceps")),  # a group listed twice
        ("chest", ("no such group",)),  # an unknown group
    ],
)
async def test_invalid_muscle_groups_are_rejected_and_store_nothing(repos, primary, secondary):
    ann = _user("ann@example.com")
    ids = {"no such group": 999_999}
    groups = MuscleGroupsIn(_group(primary), tuple(ids.get(g) or _group(g) for g in secondary))
    new = CustomExerciseIn("Mine", DbLevel.BEGINNER, EquipmentType.NONE, True, True, groups)
    existing = await _create(repos, ann, "Existing")
    before = _exercise_state(existing.id)

    assert await repos.custom.create(ann, new) == WriteError.INVALID_MUSCLE_GROUPS
    assert await repos.custom.update(ann, existing.id, {}, groups) == (
        WriteError.INVALID_MUSCLE_GROUPS
    )
    assert _exercise_state(existing.id) == before
    assert (await repos.library.list_exercises(ann, custom_only=True)).total == 1


async def test_the_limit_per_user(repos, monkeypatch):
    monkeypatch.setattr(custom_exercises, "CUSTOM_EXERCISE_LIMIT", 2)
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    await _create(repos, ann, "One")
    await _create(repos, ann, "Two")

    assert await repos.custom.create(ann, _new("Three")) == WriteError.LIMIT_REACHED
    await _create(repos, bob, "Three")  # per user


async def test_update_changes_fields_and_replaces_the_groups(repos):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press")

    updated = await repos.custom.update(
        ann,
        mine.id,
        {"name": "My row", "equipment": EquipmentType.GYM, "instruction": "Pull."},
        MuscleGroupsIn(_group("back"), (_group("biceps"),)),
    )

    assert (updated.name, updated.equipment, updated.instruction) == (
        "My row",
        EquipmentType.GYM,
        "Pull.",
    )
    assert [(g.group_name, g.is_primary) for g in updated.muscle_groups] == [
        ("back", True),
        ("biceps", False),
    ]
    assert await repos.library.get_exercise(ann, mine.id) == updated


async def test_update_never_writes_user_id_or_unknown_columns(repos):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    mine = await _create(repos, ann, "My press")

    for changes in ({"user_id": bob}, {"id": 1}, {"user_id": None}):
        with pytest.raises(ValueError, match="not an updatable exercise field"):
            await repos.custom.update(ann, mine.id, changes)
    assert (await repos.library.get_exercise(ann, mine.id)).is_custom


# ---------------------------------------------------------------- owner scope


async def test_update_and_delete_by_another_user_change_nothing(repos):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    mine = await _create(repos, ann, "My press")
    before = _exercise_state(mine.id)

    assert await repos.custom.update(bob, mine.id, {"name": "Taken"}) == WriteError.NOT_FOUND
    groups = MuscleGroupsIn(_group("back"))
    assert await repos.custom.update(bob, mine.id, {}, groups) == WriteError.NOT_FOUND
    assert await repos.custom.delete(bob, mine.id) == WriteError.NOT_FOUND
    assert _exercise_state(mine.id) == before


async def test_library_exercises_are_read_only(repos):
    ann = _user("ann@example.com")
    library = _library_exercise()
    before = _exercise_state(library)

    assert await repos.custom.update(ann, library, {"name": "Mine now"}) == WriteError.NOT_FOUND
    assert await repos.custom.delete(ann, library) == WriteError.NOT_FOUND
    assert _exercise_state(library) == before


async def test_create_for_an_unknown_user_is_not_found(repos):
    assert await repos.custom.create(999_999, _new("Orphan")) == WriteError.NOT_FOUND


# ---------------------------------------------------------------- delete


async def test_delete_removes_an_unused_exercise_and_its_groups(repos):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press")

    assert await repos.custom.delete(ann, mine.id) is None
    assert _exercise_state(mine.id) == (None, ())
    assert await repos.custom.delete(ann, mine.id) == WriteError.NOT_FOUND


async def _use_in_plan(repos, user_id, exercise_id):
    session_exercise = _plan(user_id, _library_exercise())
    async with repos.plans() as store:
        assert await store.set_session_exercise(session_exercise, {"exercise_id": exercise_id})


async def _use_as_original(repos, user_id, exercise_id):
    session_exercise = _plan(user_id, _library_exercise())
    async with repos.plans() as store:
        values = {"exercise_id": _library_exercise(skip=1), "original_exercise_id": exercise_id}
        assert await store.set_session_exercise(session_exercise, values)


async def _use_in_workout(repos, user_id, exercise_id):
    async with repos.workouts() as store:
        assert await store.insert_workout(user_id, _workout(exercise_id), [None])


async def _use_in_record(repos, user_id, exercise_id):
    async with repos.workouts() as store:
        workout_id = await store.insert_workout(user_id, _workout(_library_exercise()), [None])
        assert await store.replace_record(
            user_id, exercise_id, workout_id, Decimal("60"), 10, Decimal("80"), TODAY
        )


USES = [_use_in_plan, _use_as_original, _use_in_workout, _use_in_record]


@pytest.mark.parametrize("use", USES, ids=lambda f: f.__name__)
async def test_delete_of_an_exercise_in_use_is_refused(repos, use):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press")
    await use(repos, ann, mine.id)
    before = _exercise_state(mine.id)

    assert await repos.custom.delete(ann, mine.id) == WriteError.IN_USE
    assert _exercise_state(mine.id) == before


async def test_the_delete_checks_exactly_the_deferred_exercise_foreign_keys(seeded):
    deferred = _sql(
        "SELECT conname FROM pg_constraint WHERE confrelid = 'exercise'::regclass"
        " AND condeferrable AND condeferred"
    ).scalars()
    assert set(deferred) == set(EXERCISE_REFERENCES)


# ---------------------------------------------------------------- writes (D26)


async def _draft(repos, user_id, exercise_id) -> bool:
    request = PlanRequest(Goal.STRENGTH, 1, DifficultyLevel.ADVANCED, Equipment.GYM)
    planned = PlanExercise(exercise_id, 1, 3, 10, 60)
    plan = GeneratedPlan("Plan", (PlanSession(1, "Full Body", 1, 60, (planned,)),), ())
    async with repos.plans() as store:
        return await store.replace_draft(user_id, request, plan) is not None


async def _swap(repos, user_id, exercise_id) -> bool:
    library = _library_exercise()
    session_exercise = _plan(user_id, library)
    async with repos.plans() as store:
        values = {"exercise_id": exercise_id, "original_exercise_id": library}
        return await store.set_session_exercise(session_exercise, values)


async def _swap_original(repos, user_id, exercise_id) -> bool:
    session_exercise = _plan(user_id, _library_exercise())
    async with repos.plans() as store:
        values = {"exercise_id": _library_exercise(skip=1), "original_exercise_id": exercise_id}
        return await store.set_session_exercise(session_exercise, values)


async def _log(repos, user_id, exercise_id) -> bool:
    async with repos.workouts() as store:
        return await store.insert_workout(user_id, _workout(exercise_id), [None]) is not None


async def _relog(repos, user_id, exercise_id) -> bool:
    async with repos.workouts() as store:
        workout_id = await store.insert_workout(user_id, _workout(_library_exercise()), [None])
    async with repos.workouts() as store:
        return await store.replace_workout(user_id, workout_id, _workout(exercise_id), [None])


async def _record(repos, user_id, exercise_id) -> bool:
    async with repos.workouts() as store:
        workout_id = await store.insert_workout(user_id, _workout(_library_exercise()), [None])
        record_id = await store.replace_record(
            user_id, exercise_id, workout_id, Decimal("60"), 10, Decimal("80"), TODAY
        )
        return record_id is not None


WRITES = [_draft, _swap, _swap_original, _log, _relog, _record]


@pytest.mark.parametrize("write", WRITES, ids=lambda f: f.__name__.strip("_"))
async def test_no_write_can_reference_another_users_custom_exercise(repos, write):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    mine = await _create(repos, ann, "My press")

    assert await write(repos, bob, mine.id) is False
    assert _references(mine.id) == 0
    assert await write(repos, ann, mine.id) is True  # the owner may
    assert _references(mine.id) == 1


async def test_writes_still_accept_library_exercises(repos):
    bob = _user("bob@example.com")
    for write in WRITES:
        assert await write(repos, bob, _library_exercise(skip=2)) is True, write.__name__


# ---------------------------------------------------------------- concurrency (D26)

IMMEDIATE = f"SET CONSTRAINTS {', '.join(EXERCISE_REFERENCES)} IMMEDIATE"


async def test_swap_first_then_delete_waits_and_answers_in_use(repos):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press")
    session_exercise = _plan(ann, _library_exercise())
    swapped = asyncio.Event()

    async def swap():
        async with repos.plans() as store:
            ok = await store.set_session_exercise(session_exercise, {"exercise_id": mine.id})
            swapped.set()
            await asyncio.sleep(0.5)  # holds FOR KEY SHARE on the exercise until commit
            return ok

    async def delete():
        await swapped.wait()
        return await repos.custom.delete(ann, mine.id)

    # gather re-raises any exception, so an IntegrityError fails the test
    assert await asyncio.gather(swap(), delete()) == [True, WriteError.IN_USE]
    assert _references(mine.id) == 1


async def test_delete_first_then_swap_waits_and_answers_not_found(repos):
    ann = _user("ann@example.com")
    mine = await _create(repos, ann, "My press")
    session_exercise = _plan(ann, _library_exercise())
    deleted = asyncio.Event()

    async def delete():
        # the repository's delete, held open until the swap is waiting
        async with repos.sessions.begin() as session:
            await session.execute(text(IMMEDIATE))
            await session.execute(
                text("DELETE FROM exercise WHERE id = :e AND user_id = :u"),
                {"e": mine.id, "u": ann},
            )
            deleted.set()
            await asyncio.sleep(0.5)

    async def swap():
        await deleted.wait()
        async with repos.plans() as store:
            return await store.set_session_exercise(session_exercise, {"exercise_id": mine.id})

    assert await asyncio.gather(delete(), swap()) == [None, False]
    assert _exercise_state(mine.id) == (None, ())
    assert _references(mine.id) == 0


# ---------------------------------------------------------------- account deletion


@pytest.mark.parametrize(
    "uses",
    [[_use_in_plan], [_use_in_workout], [_use_in_record], USES],
    ids=["plan", "workout", "record", "all"],
)
async def test_deleting_a_user_removes_their_custom_exercises(repos, uses):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    mine = await _create(repos, ann, "Shared name")
    bobs = await _create(repos, bob, "Shared name")
    for use in uses:
        await use(repos, ann, mine.id)
    library = (await repos.library.list_exercises(0, custom_only=False)).total

    _sql("DELETE FROM app_user WHERE id = :u", u=ann)  # one statement, as the account deletion

    assert _exercise_state(mine.id) == (None, ())
    assert _references(mine.id) == 0
    assert _exercise_state(bobs.id)[0] is not None
    assert (await repos.library.list_exercises(0, custom_only=False)).total == library


async def test_a_cross_user_reference_blocks_deleting_the_owner_at_commit(repos):
    """What D26's scoped writes prevent: inserted here behind the repositories' back."""
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    mine = await _create(repos, ann, "My press")
    _sql(
        "INSERT INTO personal_record (user_id, exercise_id, max_weight, max_reps, e1rm,"
        " achieved_date) VALUES (:u, :e, 60, 10, 80, :d)",
        u=bob,
        e=mine.id,
        d=date.today(),
    )

    with pytest.raises(IntegrityError, match="personal_record_exercise_id_fkey"):
        _sql("DELETE FROM app_user WHERE id = :u", u=ann)
    assert _exercise_state(mine.id)[0] is not None
