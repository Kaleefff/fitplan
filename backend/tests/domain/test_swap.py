"""algorithms.md 4.9: which exercise may replace a planned one (B-13)."""

import pytest

from app.domain.constants import DifficultyLevel, Equipment, InjurySeverity
from app.domain.training import ActiveInjury, ExerciseInfo, swap_problems

BEGINNER, INTERMEDIATE = DifficultyLevel.BEGINNER, DifficultyLevel.INTERMEDIATE
NONE, HOME, GYM = Equipment.NONE, Equipment.HOME, Equipment.GYM
SHOULDER_STRAIN = 1


def _exercise(id_, group="chest", level=BEGINNER, equipment=NONE, secondary=(), injury_types=()):
    return ExerciseInfo(
        id=id_,
        difficulty_level=level,
        equipment=equipment,
        is_compound=True,
        primary_group=group,
        secondary_groups=frozenset(secondary),
        excluded_for_injury_types=frozenset(injury_types),
    )


PUSH_UP = _exercise(1, secondary=("triceps", "shoulders"))
SESSION = frozenset({1, 50})  # push-up and a back exercise


def _problems(candidate, level=INTERMEDIATE, equipment=HOME, injuries=()):
    return swap_problems(PUSH_UP, candidate, SESSION, level, equipment, list(injuries))


def test_an_eligible_exercise_of_the_same_group_is_allowed():
    assert _problems(_exercise(2, level=INTERMEDIATE, equipment=HOME)) == []


@pytest.mark.parametrize(
    ("candidate", "problems"),
    [
        (None, ["unknown_exercise"]),
        (PUSH_UP, ["same_exercise"]),
        (_exercise(3, group="back"), ["other_muscle_group"]),
        (_exercise(50, group="chest"), ["already_in_session"]),
        (_exercise(4, level=DifficultyLevel.ADVANCED), ["above_level"]),
        (_exercise(5, equipment=GYM), ["needs_equipment"]),
        (
            _exercise(6, group="back", level=DifficultyLevel.ADVANCED, equipment=GYM),
            ["other_muscle_group", "above_level", "needs_equipment"],
        ),
    ],
)
def test_each_failing_rule_is_listed_in_order(candidate, problems):
    assert _problems(candidate) == problems


def test_the_plan_snapshot_limits_level_and_equipment():
    gym_press = _exercise(7, level=INTERMEDIATE, equipment=GYM)

    assert _problems(gym_press, level=BEGINNER, equipment=NONE) == [
        "above_level",
        "needs_equipment",
    ]
    assert _problems(gym_press, level=INTERMEDIATE, equipment=GYM) == []


@pytest.mark.parametrize(
    ("candidate", "injury"),
    [
        # rule 1: listed for the injury type
        (
            _exercise(8, injury_types=(SHOULDER_STRAIN,)),
            ActiveInjury(SHOULDER_STRAIN, "core", InjurySeverity.MILD),
        ),
        # rule 2: its primary group is the affected one
        (_exercise(9), ActiveInjury(2, "chest", InjurySeverity.MILD)),
        # rule 3: moderate or severe and the affected group is secondary
        (
            _exercise(10, secondary=("shoulders",)),
            ActiveInjury(2, "shoulders", InjurySeverity.MODERATE),
        ),
    ],
)
def test_an_injury_excluded_exercise_is_rejected(candidate, injury):
    assert _problems(candidate, injuries=[injury]) == ["excluded_by_injury"]


def test_a_mild_injury_of_a_secondary_group_does_not_exclude():
    candidate = _exercise(11, secondary=("shoulders",))

    assert _problems(candidate, injuries=[ActiveInjury(2, "shoulders", InjurySeverity.MILD)]) == []
