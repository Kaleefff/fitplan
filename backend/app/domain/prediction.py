"""Goal date prediction from the weight trend (algorithms.md section 9; FR-R4)."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from itertools import pairwise

from app.domain.constants import (
    GOAL_REACHED_TOLERANCE_KG,
    LOW_FIT_R2,
    LOW_TRAINING_COMPLIANCE_PCT,
    MAX_DAYS_TO_GOAL,
    MAX_GAP_DAYS,
    MIN_SLOPE_KG_PER_DAY,
    PREDICTION_MIN_SPAN_DAYS,
    PREDICTION_MIN_WEIGH_INS,
    PREDICTION_WINDOW_DAYS,
)


class PredictionStatus(StrEnum):
    OK = "ok"
    NO_TARGET = "no_target"
    INSUFFICIENT_DATA = "insufficient_data"
    GOAL_REACHED = "goal_reached"
    NO_PROGRESS = "no_progress"
    MOVING_AWAY = "moving_away"


class PredictionWarning(StrEnum):
    LOW_FIT = "low_fit"
    GAPS = "gaps"
    LOW_TRAINING_COMPLIANCE = "low_training_compliance"


@dataclass(frozen=True)
class GoalPrediction:
    status: PredictionStatus
    estimated_date: date | None = None
    slope_kg_per_day: float | None = None
    r_squared: float | None = None
    warnings: list[PredictionWarning] = field(default_factory=list)

    @property
    def slope_kg_per_week(self) -> float | None:
        return None if self.slope_kg_per_day is None else self.slope_kg_per_day * 7

    @property
    def irregular_data(self) -> bool:
        return bool(self.warnings)


def _fit(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least-squares line y = a + b x; returns (a, b, R^2)."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for _, y in points)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    r_squared = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return intercept, slope, r_squared


def predict_goal(
    weigh_ins: list[tuple[date, Decimal]],
    target_kg: Decimal | None,
    today: date,
    training_compliance_pct: float | None = None,
) -> GoalPrediction:
    """`weigh_ins` may cover any period; only the last 28 days including today are used."""
    if target_kg is None:
        return GoalPrediction(PredictionStatus.NO_TARGET)

    window_start = today - timedelta(days=PREDICTION_WINDOW_DAYS - 1)
    window = sorted((d, w) for d, w in weigh_ins if window_start <= d <= today)
    if (
        len(window) < PREDICTION_MIN_WEIGH_INS
        or (window[-1][0] - window[0][0]).days < PREDICTION_MIN_SPAN_DAYS
    ):
        return GoalPrediction(PredictionStatus.INSUFFICIENT_DATA)

    first_day = window[0][0]
    points = [(float((d - first_day).days), float(w)) for d, w in window]
    intercept, slope, r_squared = _fit(points)
    last_day = window[-1][0]
    fitted_current = intercept + slope * points[-1][0]
    target = float(target_kg)

    warnings = []
    if r_squared < LOW_FIT_R2:
        warnings.append(PredictionWarning.LOW_FIT)
    if any((b[0] - a[0]).days > MAX_GAP_DAYS for a, b in pairwise(window)):
        warnings.append(PredictionWarning.GAPS)
    compliance = training_compliance_pct
    if compliance is not None and compliance < LOW_TRAINING_COMPLIANCE_PCT:
        warnings.append(PredictionWarning.LOW_TRAINING_COMPLIANCE)

    def result(status: PredictionStatus, estimated: date | None = None) -> GoalPrediction:
        return GoalPrediction(status, estimated, slope, r_squared, warnings)

    if abs(fitted_current - target) <= GOAL_REACHED_TOLERANCE_KG:
        return result(PredictionStatus.GOAL_REACHED)
    if abs(slope) < MIN_SLOPE_KG_PER_DAY:
        return result(PredictionStatus.NO_PROGRESS)
    days_to_go = (target - fitted_current) / slope
    if days_to_go < 0:
        return result(PredictionStatus.MOVING_AWAY)
    if days_to_go > MAX_DAYS_TO_GOAL:
        return result(PredictionStatus.NO_PROGRESS)
    whole_days = int(Decimal(str(days_to_go)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return result(PredictionStatus.OK, last_day + timedelta(days=whole_days))
