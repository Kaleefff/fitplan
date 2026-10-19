"""Plan compliance in % (algorithms.md section 7; FR-R2). Results are unrounded."""

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal

from app.domain.constants import DIET_COMPLIANCE_TOLERANCE


def workout_compliance(
    completed_workouts: int, sessions_per_week: int, overlap_days: int
) -> float | None:
    """Completed workouts / (sessions per week x overlapping plan weeks) x 100.

    `overlap_days` is the number of days of the period covered by the active plan;
    weeks are counted as days / 7. None when nothing was planned.
    """
    planned = sessions_per_week * overlap_days / 7
    if planned <= 0:
        return None
    return completed_workouts / planned * 100


def diet_compliance(
    days: Iterable[date], logged_kcal: Mapping[date, Decimal], target_kcal: int
) -> float | None:
    """Share of days whose logged kcal is within +/-10 % of the target, x 100.

    `days` are the days of the period from the plan start; a day without logs
    counts as not compliant. None for an empty period.
    """
    period = list(days)
    if not period:
        return None
    target = Decimal(target_kcal)
    tolerance = target * DIET_COMPLIANCE_TOLERANCE
    compliant = sum(
        1 for day in period if day in logged_kcal and abs(logged_kcal[day] - target) <= tolerance
    )
    return compliant / len(period) * 100
