"""Training plan generator (algorithms.md section 4; FR-P1, FR-P2, FR-P3, FR-P7).

Pure functions: the caller loads the exercise catalogue and the active injuries,
stores the returned draft and turns `InsufficientExercisesError` into 422
`insufficient_exercises`. Muscle groups are identified by their seeded names.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from app.domain.constants import (
    DURATION_STEP_MINUTES,
    EQUIPMENT_ORDER,
    EXERCISES_PER_SESSION,
    FULL_SETS_MAX_EXERCISES,
    GROUP_PRIORITY,
    LEVEL_ORDER,
    MAIN_GROUPS,
    MIN_SETS,
    SECONDS_PER_SET,
    SESSION_BASE_SECONDS,
    SESSION_GROUPS,
    SETS_REPS_REST,
    SEVERE_INJURY,
    SPLITS,
    DifficultyLevel,
    Equipment,
    Goal,
    InjurySeverity,
)


@dataclass(frozen=True)
class ExerciseInfo:
    id: int
    difficulty_level: DifficultyLevel
    equipment: Equipment
    is_compound: bool
    primary_group: str
    secondary_groups: frozenset[str] = frozenset()
    # injury types listed for it in injury_type_excluded_exercise
    excluded_for_injury_types: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ActiveInjury:
    injury_type_id: int
    affected_group: str
    severity: InjurySeverity


@dataclass(frozen=True)
class PlanExercise:
    exercise_id: int
    sort_order: int
    sets: int
    reps: int
    rest_seconds: int
    # planned_weight stays NULL until the baseline workout (6.4)


@dataclass(frozen=True)
class PlanSession:
    session_order: int
    session_name: str
    day_of_week: int  # 1 = Monday
    estimated_duration: int  # minutes
    exercises: tuple[PlanExercise, ...]


@dataclass(frozen=True)
class GeneratedPlan:
    plan_name: str
    sessions: tuple[PlanSession, ...]
    skipped_groups: tuple[str, ...]  # skipped because of injuries (4.3)


@dataclass
class InsufficientExercisesError(Exception):
    """4.4: 422 `insufficient_exercises`; `details` follow the Error model."""

    details: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 4.2, 4.3 eligibility


def fits_level_and_equipment(
    exercise: ExerciseInfo, level: DifficultyLevel, equipment: Equipment
) -> bool:
    return LEVEL_ORDER.index(exercise.difficulty_level) <= LEVEL_ORDER.index(
        level
    ) and EQUIPMENT_ORDER.index(exercise.equipment) <= EQUIPMENT_ORDER.index(equipment)


def excluded_by_injury(exercise: ExerciseInfo, injuries: list[ActiveInjury]) -> bool:
    return any(
        injury.injury_type_id in exercise.excluded_for_injury_types
        or exercise.primary_group == injury.affected_group
        or (injury.severity in SEVERE_INJURY and injury.affected_group in exercise.secondary_groups)
        for injury in injuries
    )


def is_eligible(
    exercise: ExerciseInfo,
    level: DifficultyLevel,
    equipment: Equipment,
    injuries: list[ActiveInjury],
) -> bool:
    return fits_level_and_equipment(exercise, level, equipment) and not excluded_by_injury(
        exercise, injuries
    )


def _priority(exercise: ExerciseInfo) -> tuple:
    """4.6: is_compound DESC, difficulty_level DESC, id."""
    return (not exercise.is_compound, -LEVEL_ORDER.index(exercise.difficulty_level), exercise.id)


@dataclass(frozen=True)
class _Coverage:
    eligible: dict[str, list[ExerciseInfo]]  # required group -> sorted eligible exercises
    skipped: tuple[str, ...]  # only injuries left it empty
    empty: tuple[str, ...]  # level or equipment left it empty


def _coverage(
    goal: Goal,
    level: DifficultyLevel,
    equipment: Equipment,
    injuries: list[ActiveInjury],
    exercises: list[ExerciseInfo],
) -> _Coverage:
    eligible, skipped, empty = {}, [], []
    for group in MAIN_GROUPS[goal]:
        fitting = [
            e
            for e in exercises
            if e.primary_group == group and fits_level_and_equipment(e, level, equipment)
        ]
        if not fitting:
            empty.append(group)
            continue
        allowed = sorted((e for e in fitting if not excluded_by_injury(e, injuries)), key=_priority)
        if allowed:
            eligible[group] = allowed
        else:
            skipped.append(group)
    return _Coverage(eligible, tuple(skipped), tuple(empty))


def _covered(coverage: _Coverage) -> bool:
    return not coverage.empty and bool(coverage.eligible)


def _insufficient(
    goal: Goal,
    level: DifficultyLevel,
    equipment: Equipment,
    injuries: list[ActiveInjury],
    exercises: list[ExerciseInfo],
    coverage: _Coverage,
) -> InsufficientExercisesError:
    if not coverage.empty:  # every group skipped for injuries: no suggestions
        return InsufficientExercisesError([])
    details: list[dict] = [
        {"field": "muscle_group", "code": "no_eligible_exercise", "muscle_group": group}
        for group in coverage.empty
    ]
    for tier in EQUIPMENT_ORDER[EQUIPMENT_ORDER.index(equipment) + 1 :]:
        if _covered(_coverage(goal, level, tier, injuries, exercises)):
            details.append({"code": "change_equipment", "equipment": tier.value})
            break
    goals = [
        other.value
        for other in Goal
        if other != goal and _covered(_coverage(other, level, equipment, injuries, exercises))
    ]
    if goals:
        details.append({"code": "change_goal", "goals": goals})
    return InsufficientExercisesError(details)


# ---------------------------------------------------------------- 4.5 to 4.8 the plan


def _session_groups(name: str, required: list[str]) -> list[str]:
    base, _, suffix = name.rpartition(" ")
    groups = SESSION_GROUPS[base if suffix in ("A", "B", "C") else name]  # "Upper A" -> Upper
    if groups == "full":
        return list(required)
    return [group for group in groups if group in required]


def _split(num_days: int, required: list[str]) -> list[tuple[str, int, list[str]]]:
    sessions = [(name, day, _session_groups(name, required)) for name, day in SPLITS[num_days]]
    for group in required:
        if not any(group in groups for _, _, groups in sessions):
            min(sessions, key=lambda s: len(s[2]))[2].append(group)
    # A session whose groups were all skipped for injuries trains every required group
    # (algorithms.md is silent; questions.md, B-11).
    return [(name, day, groups or list(required)) for name, day, groups in sessions]


def _picks_per_group(groups: list[str], level: DifficultyLevel, eligible) -> dict[str, int]:
    """One per group, then extra slots in GROUP_PRIORITY order, never repeating an exercise."""
    picks = dict.fromkeys(groups, 1)
    extra = max(EXERCISES_PER_SESSION[level], len(groups)) - len(groups)
    while extra > 0:
        added = False
        for group in GROUP_PRIORITY:
            if extra and group in picks and picks[group] < len(eligible[group]):
                picks[group] += 1
                extra -= 1
                added = True
        if not added:
            break
    return picks


def _sets_reps_rest(
    goal: Goal, exercise: ExerciseInfo, level: DifficultyLevel, count: int
) -> tuple[int, int, int]:
    compound, isolation = SETS_REPS_REST[goal]
    sets, reps, rest = compound if exercise.is_compound else isolation
    if level == DifficultyLevel.BEGINNER:
        sets -= 1
    if count > FULL_SETS_MAX_EXERCISES:
        sets -= 1
    return max(sets, MIN_SETS), reps, rest


def _duration_minutes(exercises: list[PlanExercise]) -> int:
    seconds = SESSION_BASE_SECONDS + sum(
        e.sets * (SECONDS_PER_SET + e.rest_seconds) for e in exercises
    )
    return math.ceil(seconds / 60 / DURATION_STEP_MINUTES) * DURATION_STEP_MINUTES


def goal_label(goal: Goal) -> str:
    """muscle_gain -> "Muscle gain", for plan names (4.8, 5.5)."""
    return goal.value.replace("_", " ").capitalize()


def plan_name(goal: Goal, num_days: int) -> str:
    """4.8: "<Goal>, <n> day(s) per week"."""
    days = "day" if num_days == 1 else "days"
    return f"{goal_label(goal)}, {num_days} {days} per week"


def generate_training_plan(
    goal: Goal,
    num_days: int,
    level: DifficultyLevel,
    equipment: Equipment,
    injuries: list[ActiveInjury],
    exercises: list[ExerciseInfo],
) -> GeneratedPlan:
    coverage = _coverage(goal, level, equipment, injuries, exercises)
    if not _covered(coverage):
        raise _insufficient(goal, level, equipment, injuries, exercises, coverage)
    required = [group for group in MAIN_GROUPS[goal] if group in coverage.eligible]

    occurrences: dict[str, int] = defaultdict(int)
    sessions = []
    for order, (name, day, groups) in enumerate(_split(num_days, required), start=1):
        picks = _picks_per_group(groups, level, coverage.eligible)
        chosen: list[ExerciseInfo] = []
        for group in groups:
            pool, count = coverage.eligible[group], picks[group]
            start = (occurrences[group] * count) % len(pool)  # k-th occurrence of the group
            chosen += [pool[(start + j) % len(pool)] for j in range(count)]
            occurrences[group] += 1
        # compound first, then larger groups (GROUP_PRIORITY), then the pick order
        chosen.sort(key=lambda e: (not e.is_compound, GROUP_PRIORITY.index(e.primary_group)))
        planned = [
            PlanExercise(e.id, sort_order, *_sets_reps_rest(goal, e, level, len(chosen)))
            for sort_order, e in enumerate(chosen, start=1)
        ]
        sessions.append(PlanSession(order, name, day, _duration_minutes(planned), tuple(planned)))

    return GeneratedPlan(plan_name(goal, num_days), tuple(sessions), coverage.skipped)
