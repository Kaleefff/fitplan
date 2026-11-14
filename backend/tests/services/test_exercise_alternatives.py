"""Which limits the alternatives of 4.9 use (B-08); the SQL is tested in tests/db/."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.core.errors import AppError
from app.db.enums import DifficultyLevel as DbLevel
from app.db.enums import EquipmentType
from app.db.repositories.library import ExerciseGroupRow, ExerciseRow
from app.domain.constants import DifficultyLevel, Equipment
from app.services.library import LibraryService
from app.services.training_plans import SwapContext

USER = 1
PUSH_UP, BENCH, ROW = 10, 11, 20
CHEST, TRICEPS = 1, 5


def _exercise(exercise_id: int, groups: tuple[ExerciseGroupRow, ...]) -> ExerciseRow:
    return ExerciseRow(
        id=exercise_id,
        name=f"exercise {exercise_id}",
        difficulty_level=DbLevel.BEGINNER,
        equipment=EquipmentType.NONE,
        is_compound=True,
        is_bodyweight=True,
        description="",
        instruction="",
        muscle_groups=groups,
    )


PUSH_UP_ROW = _exercise(
    PUSH_UP,
    (ExerciseGroupRow(CHEST, "chest", True), ExerciseGroupRow(TRICEPS, "triceps", False)),
)


class FakeLibrary:
    def __init__(self) -> None:
        self.asked: dict | None = None

    async def get_exercise(self, exercise_id: int) -> ExerciseRow | None:
        return PUSH_UP_ROW if exercise_id == PUSH_UP else None

    async def eligible_exercises(self, user_id: int, **limits) -> list[ExerciseRow]:
        self.asked = {"user_id": user_id, **limits}
        return [_exercise(BENCH, (ExerciseGroupRow(CHEST, "chest", True),))]


class FakePlans:
    def __init__(self, profile=None, context: SwapContext | None = None) -> None:
        self.profile = profile
        self.context = context

    async def profile_limits(self, user_id: int):
        return self.profile

    async def swap_context(self, user_id: int, session_exercise_id: int, *, lock=False):
        return self.context if user_id == USER and session_exercise_id == 7 else None

    @asynccontextmanager
    async def __call__(self):
        yield self


def _alternatives(plans: FakePlans, exercise_id=PUSH_UP, session_exercise_id=None):
    library = FakeLibrary()
    service = LibraryService(library, plans)
    rows = asyncio.run(service.alternatives(USER, exercise_id, session_exercise_id))
    return rows, library.asked


def _context(exercise_id=PUSH_UP) -> SwapContext:
    return SwapContext(
        exercise_id=exercise_id,
        original_exercise_id=None,
        plan_status="active",
        experience_level=DifficultyLevel.INTERMEDIATE,
        equipment=Equipment.HOME,
        session_exercise_ids=frozenset({PUSH_UP, ROW}),
    )


def test_without_a_profile_only_injuries_and_the_group_apply():
    rows, asked = _alternatives(FakePlans())

    assert [r.id for r in rows] == [BENCH]
    assert asked == {
        "user_id": USER,
        "level": None,
        "equipment": None,
        "primary_group_id": CHEST,
        "exclude_ids": {PUSH_UP},
    }


def test_the_profile_limits_level_and_equipment():
    _, asked = _alternatives(FakePlans(profile=(DifficultyLevel.BEGINNER, Equipment.NONE)))

    assert (asked["level"], asked["equipment"]) == (DbLevel.BEGINNER, EquipmentType.NONE)
    assert asked["exclude_ids"] == {PUSH_UP}


def test_a_session_exercise_uses_the_plan_snapshot_and_the_session():
    plans = FakePlans(profile=(DifficultyLevel.ADVANCED, Equipment.GYM), context=_context())

    _, asked = _alternatives(plans, session_exercise_id=7)

    assert (asked["level"], asked["equipment"]) == (DbLevel.INTERMEDIATE, EquipmentType.HOME)
    assert asked["exclude_ids"] == {PUSH_UP, ROW}


@pytest.mark.parametrize(
    ("exercise_id", "session_exercise_id", "context"),
    [
        (999, None, None),  # unknown exercise
        (PUSH_UP, 8, _context()),  # another user's or a missing session exercise
        (PUSH_UP, 7, _context(exercise_id=ROW)),  # the slot holds another exercise
    ],
)
def test_not_found(exercise_id, session_exercise_id, context):
    with pytest.raises(AppError) as error:
        _alternatives(FakePlans(context=context), exercise_id, session_exercise_id)

    assert error.value.status_code == 404
