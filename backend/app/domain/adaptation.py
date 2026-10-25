"""Adaptation and progression after a workout (algorithms.md section 6; FR-A2, FR-A4, FR-A5).

The plan changes only after an explicit signal (FR-A4). `adapt` returns None
whenever nothing changes; the caller writes a non-None result to
`session_exercise` and records it as a plan adjustment.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.constants import (
    BASELINE_REDUCE_FACTOR,
    BODYWEIGHT_MAX_REPS,
    MIN_SETS,
    PROGRESSION_STEP_KG,
    REDUCE_RPE_THRESHOLD,
    REDUCTION_FACTOR,
    RESERVE_RPE_MAX,
    WEIGHT_STEP_KG,
    BodyRegion,
)
from app.domain.rounding import round_to_step


class AdjustmentReason(StrEnum):
    BASELINE = "baseline"
    PROGRESSION = "progression"
    REDUCE_HIGH_RPE = "reduce_high_rpe"
    REDUCE_INCOMPLETE_SET = "reduce_incomplete_set"


@dataclass(frozen=True)
class PlannedExercise:
    sets: int
    reps: int
    weight_kg: Decimal | None  # None = no baseline yet
    is_bodyweight: bool
    region: BodyRegion  # region of the exercise's main muscle group


@dataclass(frozen=True)
class LoggedSet:
    reps: int
    weight_kg: Decimal
    completed: bool
    rpe: int | None = None


@dataclass(frozen=True)
class Adjustment:
    reason: AdjustmentReason
    sets: int
    reps: int
    weight_kg: Decimal | None


def reduce_signal(sets: list[LoggedSet], overall_rpe: int | None) -> AdjustmentReason | None:
    """Overall RPE >= 9 or a set that was not completed; RPE wins when both hold."""
    if overall_rpe is not None and overall_rpe >= REDUCE_RPE_THRESHOLD:
        return AdjustmentReason.REDUCE_HIGH_RPE
    if any(not s.completed for s in sets):
        return AdjustmentReason.REDUCE_INCOMPLETE_SET
    return None


def reserve_signal(
    planned: PlannedExercise, sets: list[LoggedSet], overall_rpe: int | None
) -> bool:
    """Every planned set completed with all reps at the planned weight or more (when set),
    and the highest set RPE (else the overall RPE) at most 7. No RPE at all: no signal."""
    full_sets = [
        s
        for s in sets
        if s.completed
        and s.reps >= planned.reps
        and (planned.weight_kg is None or s.weight_kg >= planned.weight_kg)
    ]
    if len(full_sets) < planned.sets:
        return False
    set_rpes = [s.rpe for s in sets if s.rpe is not None]
    rpe = max(set_rpes) if set_rpes else overall_rpe
    return rpe is not None and rpe <= RESERVE_RPE_MAX


def adapt(
    planned: PlannedExercise, sets: list[LoggedSet], overall_rpe: int | None
) -> Adjustment | None:
    reduce = reduce_signal(sets, overall_rpe)

    # Baseline: a weighted exercise without a planned weight.
    if not planned.is_bodyweight and planned.weight_kg is None:
        weights = [s.weight_kg for s in sets if s.completed and s.weight_kg > 0]
        if weights:
            factor = BASELINE_REDUCE_FACTOR if reduce else Decimal(1)
            return Adjustment(
                AdjustmentReason.BASELINE,
                planned.sets,
                planned.reps,
                round_to_step(max(weights) * factor),
            )

    # Reduction wins over progression.
    if reduce is not None:
        return _reduce(planned, reduce)

    # Progression.
    if reserve_signal(planned, sets, overall_rpe):
        return _progress(planned)

    return None


def _reduce(planned: PlannedExercise, reason: AdjustmentReason) -> Adjustment | None:
    if not planned.is_bodyweight and planned.weight_kg is not None:
        weight = planned.weight_kg
        new_weight = max(
            min(round_to_step(weight * REDUCTION_FACTOR), weight - WEIGHT_STEP_KG), Decimal(0)
        )
        if new_weight == weight:
            return None
        return Adjustment(reason, planned.sets, planned.reps, new_weight)

    new_sets = max(planned.sets - 1, MIN_SETS)
    if new_sets == planned.sets:
        return None
    return Adjustment(reason, new_sets, planned.reps, planned.weight_kg)


def _progress(planned: PlannedExercise) -> Adjustment | None:
    if planned.is_bodyweight:
        new_reps = min(planned.reps + 1, BODYWEIGHT_MAX_REPS)
        if new_reps == planned.reps:
            return None
        return Adjustment(AdjustmentReason.PROGRESSION, planned.sets, new_reps, planned.weight_kg)

    # A weighted exercise still without a planned weight (only 0 kg sets) has nothing to
    # add the step to; algorithms.md 6 is silent (questions.md, B-16).
    if planned.weight_kg is None:
        return None
    new_weight = planned.weight_kg + PROGRESSION_STEP_KG[planned.region]
    return Adjustment(AdjustmentReason.PROGRESSION, planned.sets, planned.reps, new_weight)
