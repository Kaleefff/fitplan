"""Training plan generator, algorithms.md section 4 (B-11)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.constants import (
    ALL_GROUPS,
    MAIN_GROUPS,
    MIN_SETS,
    DifficultyLevel,
    Equipment,
    Goal,
    InjurySeverity,
)
from app.domain.training import (
    ActiveInjury,
    ExerciseInfo,
    InsufficientExercisesError,
    excluded_by_injury,
    fits_level_and_equipment,
    generate_training_plan,
    is_eligible,
    plan_name,
)

BEG, INT, ADV = DifficultyLevel.BEGINNER, DifficultyLevel.INTERMEDIATE, DifficultyLevel.ADVANCED
NONE, HOME, GYM = Equipment.NONE, Equipment.HOME, Equipment.GYM

# Per group g (index i): id 10i+1 compound/beginner/none, 10i+2 compound/intermediate/home,
# 10i+3 isolation/beginner/gym, 10i+4 isolation/advanced/none.
VARIANTS = ((1, True, BEG, NONE), (2, True, INT, HOME), (3, False, BEG, GYM), (4, False, ADV, NONE))


def catalog(skip_groups: tuple[str, ...] = (), **extra: dict) -> list[ExerciseInfo]:
    exercises = [
        ExerciseInfo(10 * i + n, level, equipment, compound, group)
        for i, group in enumerate(ALL_GROUPS)
        if group not in skip_groups
        for n, compound, level, equipment in VARIANTS
    ]
    return exercises + list(extra.get("more", []))


def eid(group: str, variant: int) -> int:
    return 10 * ALL_GROUPS.index(group) + variant


def by_group(session) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for exercise in session.exercises:
        result.setdefault(ALL_GROUPS[exercise.exercise_id // 10], []).append(exercise.exercise_id)
    return result


# ---------------------------------------------------------------- 4.2, 4.3


def test_level_and_equipment_tiers():
    home_intermediate = ExerciseInfo(1, INT, HOME, True, "chest")
    assert fits_level_and_equipment(home_intermediate, INT, HOME)
    assert fits_level_and_equipment(home_intermediate, ADV, GYM)
    assert not fits_level_and_equipment(home_intermediate, BEG, GYM)
    assert not fits_level_and_equipment(home_intermediate, ADV, NONE)


def test_injury_rules():
    bench = ExerciseInfo(1, BEG, GYM, True, "chest", frozenset({"triceps"}), frozenset({7}))
    assert excluded_by_injury(bench, [ActiveInjury(7, "calves", InjurySeverity.MILD)])  # (1)
    assert excluded_by_injury(bench, [ActiveInjury(1, "chest", InjurySeverity.MILD)])  # (2)
    assert excluded_by_injury(bench, [ActiveInjury(1, "triceps", InjurySeverity.MODERATE)])  # (3)
    assert not excluded_by_injury(bench, [ActiveInjury(1, "triceps", InjurySeverity.MILD)])
    assert not is_eligible(bench, ADV, GYM, [ActiveInjury(1, "triceps", InjurySeverity.SEVERE)])


def test_plan_name():
    assert plan_name(Goal.MUSCLE_GAIN, 1) == "Muscle gain, 1 day per week"
    assert plan_name(Goal.GENERAL_FITNESS, 7) == "General fitness, 7 days per week"


# ---------------------------------------------------------------- 4.5


@pytest.mark.parametrize(
    ("days", "names", "weekdays"),
    [
        (1, ["Full Body"], [3]),
        (2, ["Full Body A", "Full Body B"], [1, 4]),
        (3, ["Full Body A", "Full Body B", "Full Body C"], [1, 3, 5]),
        (4, ["Upper A", "Lower A", "Upper B", "Lower B"], [1, 2, 4, 5]),
        (5, ["Upper", "Lower", "Push", "Pull", "Legs"], [1, 2, 4, 5, 6]),
        (6, ["Push A", "Pull A", "Legs A", "Push B", "Pull B", "Legs B"], [1, 2, 3, 4, 5, 6]),
        (
            7,
            ["Push A", "Pull A", "Legs A", "Push B", "Pull B", "Legs B", "Full Body"],
            [1, 2, 3, 4, 5, 6, 7],
        ),
    ],
)
def test_split(days, names, weekdays):
    plan = generate_training_plan(Goal.MUSCLE_GAIN, days, ADV, GYM, [], catalog())
    assert [s.session_name for s in plan.sessions] == names
    assert [s.day_of_week for s in plan.sessions] == weekdays
    assert [s.session_order for s in plan.sessions] == list(range(1, days + 1))


# ---------------------------------------------------------------- 4.6, 4.7 worked examples


def test_full_body_muscle_gain_rotates_and_trims_sets():
    """Intermediate, gym: per group [10i+2, 10i+1, 10i+3] (compound, harder first)."""
    plan = generate_training_plan(Goal.MUSCLE_GAIN, 3, INT, GYM, [], catalog())
    a, b, c = plan.sessions

    # one per group (10 > 6), the k-th occurrence starts at index k
    assert by_group(a) == {g: [eid(g, 2)] for g in ALL_GROUPS}
    assert by_group(b) == {g: [eid(g, 1)] for g in ALL_GROUPS}
    assert by_group(c) == {g: [eid(g, 3)] for g in ALL_GROUPS}
    # all compound: larger groups first
    assert [e.exercise_id for e in a.exercises][:3] == [
        eid("quadriceps", 2),
        eid("back", 2),
        eid("chest", 2),
    ]
    # 10 exercises > 8: one set fewer; compound 4x8/120 -> 3, isolation 3x12/75 -> 2
    assert {(e.sets, e.reps, e.rest_seconds) for e in a.exercises} == {(3, 8, 120)}
    assert {(e.sets, e.reps, e.rest_seconds) for e in c.exercises} == {(2, 12, 75)}
    # 600 + 10 x 3 x (45 + 120) = 5550 s = 92.5 min -> 95; 600 + 10 x 2 x 120 = 3000 s -> 50
    assert (a.estimated_duration, c.estimated_duration) == (95, 50)
    assert plan.skipped_groups == ()


def test_upper_lower_beginner_fills_extra_slots_by_priority():
    """Beginner, gym, weight loss: per group [10i+1, 10i+3]."""
    plan = generate_training_plan(Goal.WEIGHT_LOSS, 4, BEG, GYM, [], catalog())
    upper_a, lower_a, upper_b, _ = plan.sessions

    # 3 groups, 5 slots: second exercises go to back, then chest
    assert by_group(upper_a) == {
        "chest": [eid("chest", 1), eid("chest", 3)],
        "back": [eid("back", 1), eid("back", 3)],
        "shoulders": [eid("shoulders", 1)],
    }
    assert [e.exercise_id for e in upper_a.exercises] == [
        eid("back", 1),
        eid("chest", 1),
        eid("shoulders", 1),
        eid("back", 3),
        eid("chest", 3),
    ]
    # second occurrence of shoulders (1 pick) starts at index 1
    assert by_group(upper_b)["shoulders"] == [eid("shoulders", 3)]
    # calves are not a main group here; 4 groups, 1 extra slot for quadriceps
    assert set(by_group(lower_a)) == {"quadriceps", "hamstrings", "glutes", "core"}
    assert len(by_group(lower_a)["quadriceps"]) == 2
    # beginner: one set fewer; 3x12/60 and 3x15/45 both become 2 sets
    assert {(e.sets, e.reps) for e in upper_a.exercises} == {(2, 12), (2, 15)}


def test_extra_slots_never_repeat_an_exercise():
    """Beginner, none: one exercise per group, so a 3-group session stays at 3."""
    plan = generate_training_plan(Goal.STRENGTH, 6, BEG, NONE, [], catalog())
    push = plan.sessions[0]
    assert len(push.exercises) == 2  # chest, shoulders (triceps is not a main group)
    assert len({e.exercise_id for e in push.exercises}) == 2


# ---------------------------------------------------------------- 4.3 skipped, 4.4 insufficient


def test_injured_group_is_skipped():
    plan = generate_training_plan(
        Goal.MAINTENANCE, 3, ADV, GYM, [ActiveInjury(1, "chest", InjurySeverity.MILD)], catalog()
    )
    assert plan.skipped_groups == ("chest",)
    assert all("chest" not in by_group(s) for s in plan.sessions)


def test_session_left_empty_by_injuries_trains_every_required_group():
    injuries = [
        ActiveInjury(1, "chest", InjurySeverity.MILD),
        ActiveInjury(1, "shoulders", InjurySeverity.MILD),
    ]
    plan = generate_training_plan(Goal.WEIGHT_LOSS, 6, ADV, GYM, injuries, catalog())
    push_a = plan.sessions[0]
    assert set(by_group(push_a)) == {"back", "quadriceps", "hamstrings", "glutes", "core"}


def test_missing_equipment_suggests_the_next_tier_and_other_goals():
    calves_gym_only = [e for e in catalog() if e.primary_group != "calves"] + [
        ExerciseInfo(999, BEG, GYM, False, "calves")
    ]
    with pytest.raises(InsufficientExercisesError) as error:
        generate_training_plan(Goal.MUSCLE_GAIN, 3, ADV, HOME, [], calves_gym_only)

    assert error.value.details == [
        {"field": "muscle_group", "code": "no_eligible_exercise", "muscle_group": "calves"},
        {"code": "change_equipment", "equipment": "gym"},
        {
            "code": "change_goal",
            "goals": ["weight_loss", "strength", "maintenance", "general_fitness", "endurance"],
        },
    ]


def test_no_equipment_suggestion_when_no_tier_helps():
    with pytest.raises(InsufficientExercisesError) as error:
        generate_training_plan(Goal.MUSCLE_GAIN, 3, ADV, NONE, [], catalog(skip_groups=("calves",)))
    assert [d["code"] for d in error.value.details] == ["no_eligible_exercise", "change_goal"]


def test_every_group_skipped_is_insufficient_without_suggestions():
    injuries = [ActiveInjury(1, g, InjurySeverity.MILD) for g in MAIN_GROUPS[Goal.STRENGTH]]
    with pytest.raises(InsufficientExercisesError) as error:
        generate_training_plan(Goal.STRENGTH, 3, ADV, GYM, injuries, catalog())
    assert error.value.details == []


# ---------------------------------------------------------------- property (Done of B-11)

injuries_strategy = st.lists(
    st.builds(
        ActiveInjury,
        st.integers(1, 3),
        st.sampled_from(ALL_GROUPS),
        st.sampled_from(list(InjurySeverity)),
    ),
    max_size=4,
)


def property_catalog() -> list[ExerciseInfo]:
    """catalog() plus exercises with secondary groups and per-injury-type exclusions."""
    more = [
        ExerciseInfo(
            500 + i,
            BEG,
            NONE,
            True,
            group,
            frozenset({ALL_GROUPS[(i + 1) % len(ALL_GROUPS)]}),
            frozenset({1 + i % 3}),
        )
        for i, group in enumerate(ALL_GROUPS)
    ]
    return catalog(more=more)


@settings(max_examples=300, deadline=None)
@given(
    goal=st.sampled_from(list(Goal)),
    days=st.integers(1, 7),
    level=st.sampled_from(list(DifficultyLevel)),
    equipment=st.sampled_from(list(Equipment)),
    injuries=injuries_strategy,
)
def test_every_required_group_is_trained_and_nothing_ineligible(
    goal, days, level, equipment, injuries
):
    exercises = property_catalog()
    by_id = {e.id: e for e in exercises}
    try:
        plan = generate_training_plan(goal, days, level, equipment, injuries, exercises)
    except InsufficientExercisesError as error:
        # every group has a beginner/no-equipment exercise: only injuries can empty all
        assert error.details == []
        return

    required = set(MAIN_GROUPS[goal]) - set(plan.skipped_groups)
    trained = {by_id[e.exercise_id].primary_group for s in plan.sessions for e in s.exercises}
    assert trained == required
    assert len(plan.sessions) == days
    assert len({s.day_of_week for s in plan.sessions}) == days
    for session in plan.sessions:
        ids = [e.exercise_id for e in session.exercises]
        assert len(ids) == len(set(ids))
        assert [e.sort_order for e in session.exercises] == list(range(1, len(ids) + 1))
        for planned in session.exercises:
            assert is_eligible(by_id[planned.exercise_id], level, equipment, injuries)
            assert planned.sets >= MIN_SETS
        assert session.estimated_duration % 5 == 0
