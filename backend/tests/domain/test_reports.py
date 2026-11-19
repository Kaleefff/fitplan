"""Progress reports, algorithms.md 8 and api-rules.md "Reports" (B-25)."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.constants import ReportType
from app.domain.prediction import GoalPrediction, PredictionStatus, PredictionWarning
from app.domain.reports import period_problems, report_figures, report_type
from tests.domain.test_analytics import DATA, TODAY, day


@pytest.mark.parametrize(
    ("start", "end", "kind"),
    [
        (date(2026, 11, 9), date(2026, 11, 15), ReportType.WEEKLY),  # Monday-Sunday
        (date(2026, 11, 10), date(2026, 11, 16), ReportType.CUSTOM),  # Tuesday-Monday
        (date(2026, 2, 1), date(2026, 2, 28), ReportType.MONTHLY),
        (date(2028, 2, 1), date(2028, 2, 28), ReportType.CUSTOM),  # leap year: 29 days
        (date(2026, 10, 1), date(2026, 10, 30), ReportType.CUSTOM),
        (date(2026, 11, 9), date(2026, 11, 9), ReportType.CUSTOM),
    ],
)
def test_report_type_follows_the_period(start, end, kind):
    assert report_type(start, end) == kind


def test_period_rules():
    today = date(2026, 11, 19)
    assert period_problems(date(2025, 11, 19), today, today) == []  # 366 days
    codes = [
        [(p["field"], p["code"]) for p in period_problems(start, end, today)]
        for start, end in (
            (date(2025, 11, 18), today),  # 367 days
            (today, date(2026, 11, 18)),  # end before start
            (today, date(2026, 11, 20)),  # after today
        )
    ]
    assert codes == [
        [("body.period_end", "invalid_value")],
        [("body.period_end", "invalid_value")],
        [("body.period_end", "future_date")],
    ]


def test_figures_of_the_hand_computed_week_round_as_the_analytics():
    """The week of test_analytics: 2 workouts, 1430 kg, 3 sessions a week over 6 covered
    days = 2.57 planned -> 3; compliance 77.78 -> 77.8 %, diet 20 %."""
    prediction = GoalPrediction(
        PredictionStatus.OK, date(2027, 1, 1), warnings=[PredictionWarning.GAPS]
    )

    f = report_figures(day(6), TODAY, DATA, prediction)

    assert f.report_type == ReportType.CUSTOM  # Thursday to Wednesday
    assert (f.weight_difference, f.training_volume, f.avg_cals_daily) == (
        D("-0.60"),
        D("1430.0"),
        2000,
    )
    assert (f.training_sessions_completed, f.training_sessions_planned) == (2, 3)
    assert (f.workout_compliance_pct, f.diet_compliance_pct) == (D("77.8"), D("20.0"))
    assert [(k.exercise_id, k.first_e1rm, k.best_e1rm) for k in f.key_lifts] == [
        (10, D("80.00"), D("81.67"))
    ]
    assert (f.estimated_goal_completion_date, f.irregular_data) == (date(2027, 1, 1), True)


def test_a_period_without_data_has_zero_volume_and_null_metrics():
    empty = type(DATA)([], [], [], {}, None, None)

    f = report_figures(day(6), TODAY, empty, GoalPrediction(PredictionStatus.NO_TARGET))

    assert (f.weight_difference, f.training_volume, f.training_sessions_completed) == (
        None,
        D(0),
        0,
    )
    assert (f.training_sessions_planned, f.workout_compliance_pct, f.key_lifts) == (0, None, ())
    assert (f.estimated_goal_completion_date, f.irregular_data) == (None, False)
