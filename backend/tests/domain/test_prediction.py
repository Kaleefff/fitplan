"""Goal prediction (algorithms.md section 9).

The section lists scenario outcomes without their weigh-ins; the fixtures below are
hand-computed to give exactly those outcomes (today 2026-10-14, target 78).
"""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.domain.prediction import PredictionStatus, PredictionWarning, predict_goal

TODAY = date(2026, 10, 14)


def weekly(*weights, end=TODAY):
    """One weigh-in every 7 days, the last one on `end`."""
    n = len(weights)
    return [(end - timedelta(days=7 * (n - 1 - i)), D(w)) for i, w in enumerate(weights)]


# -0.07 kg/day; fitted current 82.06, (78 - 82.06) / -0.07 = 58 days
STEADY = weekly("83.53", "83.04", "82.55", "82.06")

# fitted line -0.26 kg/week ending at 82.83, residuals orthogonal to it; gaps <= 5 days
SCATTERED = [
    (TODAY - timedelta(days=27 - day), D(weight))
    for day, weight in [
        (0, "84.48"), (4, "82.88"), (9, "84.12"), (13, "82.52"),
        (18, "83.77"), (22, "82.17"), (27, "83.42"),
    ]
]  # fmt: skip


def test_scenario_steady_loss():
    result = predict_goal(STEADY, D("78"), TODAY, 90.0)
    assert result.status == PredictionStatus.OK
    assert result.estimated_date == date(2026, 12, 11)
    assert round(result.slope_kg_per_week, 2) == -0.49
    assert result.r_squared == pytest.approx(1.0)
    assert result.warnings == []
    assert result.irregular_data is False


def test_scenario_scattered_with_low_compliance():
    result = predict_goal(SCATTERED, D("78"), TODAY, 50.0)
    assert result.status == PredictionStatus.OK
    assert result.estimated_date == date(2027, 2, 21)
    assert round(result.slope_kg_per_week, 2) == -0.26
    assert round(result.r_squared, 2) == 0.18
    assert result.warnings == [PredictionWarning.LOW_FIT, PredictionWarning.LOW_TRAINING_COMPLIANCE]
    assert result.irregular_data is True


def test_scenario_gaining():
    result = predict_goal(weekly("76", "76.5", "77", "77.5"), D("75"), TODAY)
    assert result.status == PredictionStatus.MOVING_AWAY
    assert result.estimated_date is None


def test_scenario_two_weigh_ins():
    result = predict_goal(weekly("80", "79.5"), D("78"), TODAY)
    assert result.status == PredictionStatus.INSUFFICIENT_DATA


# --- rules around the scenarios ----------------------------------------------


def test_only_last_28_days_are_used():
    old = [(TODAY - timedelta(days=60), D("95"))]
    result = predict_goal(old + STEADY, D("78"), TODAY)
    assert result.estimated_date == date(2026, 12, 11)


def test_no_target():
    assert predict_goal(weekly("80", "79"), None, TODAY).status == PredictionStatus.NO_TARGET


def test_span_under_seven_days_is_insufficient():
    weigh_ins = [(TODAY - timedelta(days=d), D("80")) for d in (6, 3, 0)]
    result = predict_goal(weigh_ins, D("77"), TODAY)
    assert result.status == PredictionStatus.INSUFFICIENT_DATA


def test_flat_weight_is_no_progress():
    result = predict_goal(weekly("80", "80", "80", "80"), D("75"), TODAY)
    assert result.status == PredictionStatus.NO_PROGRESS


def test_goal_far_away_is_no_progress():
    # 0.1 kg per week = 0.0143 kg/day; 30 kg to go = 2100 days
    result = predict_goal(weekly("100.3", "100.2", "100.1", "100"), D("70"), TODAY)
    assert result.status == PredictionStatus.NO_PROGRESS


def test_goal_reached():
    result = predict_goal(weekly("79.5", "79", "78.5", "78.4"), D("78"), TODAY)
    assert result.status == PredictionStatus.GOAL_REACHED


def test_irregular_data_warnings():
    weigh_ins = [
        (TODAY - timedelta(days=26), D("80")),
        (TODAY - timedelta(days=14), D("78")),  # 12-day gap
        (TODAY - timedelta(days=10), D("80.5")),
        (TODAY - timedelta(days=5), D("77.5")),
        (TODAY, D("79")),
    ]
    result = predict_goal(weigh_ins, D("70"), TODAY, training_compliance_pct=50.0)
    assert result.status == PredictionStatus.OK
    assert result.estimated_date is not None
    assert result.warnings == [
        PredictionWarning.LOW_FIT,
        PredictionWarning.GAPS,
        PredictionWarning.LOW_TRAINING_COMPLIANCE,
    ]
    assert result.irregular_data is True
