"""Goal prediction (algorithms.md section 9).

The vectors printed in algorithms.md do not list their weigh-ins (they come
from scripts/algorithms_reference.py, which is not in the repository), so these
fixtures are hand-computed instead.
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


def test_steady_loss_gives_a_date():
    # -0.5 kg per week, fitted current 78.5, target 77 -> 1.5 / (0.5/7) = 21 days
    result = predict_goal(weekly("80", "79.5", "79", "78.5"), D("77"), TODAY, 90.0)
    assert result.status == PredictionStatus.OK
    assert result.estimated_date == date(2026, 11, 4)
    assert result.slope_kg_per_week == pytest.approx(-0.5)
    assert result.r_squared == pytest.approx(1.0)
    assert result.warnings == []
    assert result.irregular_data is False


def test_only_last_28_days_are_used():
    old = [(TODAY - timedelta(days=60), D("95"))]
    result = predict_goal(old + weekly("80", "79.5", "79", "78.5"), D("77"), TODAY)
    assert result.estimated_date == date(2026, 11, 4)


def test_no_target():
    assert predict_goal(weekly("80", "79"), None, TODAY).status == PredictionStatus.NO_TARGET


def test_two_weigh_ins_are_insufficient():
    result = predict_goal(weekly("80", "79.5"), D("77"), TODAY)
    assert result.status == PredictionStatus.INSUFFICIENT_DATA


def test_span_under_seven_days_is_insufficient():
    weigh_ins = [(TODAY - timedelta(days=d), D("80")) for d in (6, 3, 0)]
    result = predict_goal(weigh_ins, D("77"), TODAY)
    assert result.status == PredictionStatus.INSUFFICIENT_DATA


def test_moving_away():
    result = predict_goal(weekly("74", "74.5", "75", "75.5"), D("72"), TODAY)
    assert result.status == PredictionStatus.MOVING_AWAY
    assert result.estimated_date is None


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
