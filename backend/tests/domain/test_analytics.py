"""Analytics metrics and series, algorithms.md sections 7 and 8 (B-23).

Every expected number is computed by hand in the comments.
"""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.domain.analytics import (
    ActivePlan,
    AnalyticsData,
    LoggedSetRow,
    enough_history,
    key_lifts,
    series,
    summary,
    window,
)

TODAY = date(2026, 10, 14)  # a Wednesday


def day(n: int) -> date:
    """n days before today."""
    return TODAY - timedelta(days=n)


def row(workout, n, exercise, reps, weight, completed=True, name=None):
    return LoggedSetRow(
        workout, day(n), exercise, name or f"E{exercise}", reps, D(weight), completed
    )


DATA = AnalyticsData(
    weigh_ins=[(day(6), D("80.0")), (day(2), D("79.4"))],
    workouts=[(1, day(5)), (2, day(1))],
    sets=[
        row(1, 5, 10, 10, 60),  # 600
        row(1, 5, 10, 8, 60),  # 480
        row(1, 5, 11, 12, 0),  # bodyweight: no tonnage
        row(2, 1, 10, 5, 70),  # 350
        row(2, 1, 10, 5, 70, completed=False),  # not completed: no tonnage
    ],
    daily_kcal={day(4): D("2000"), day(3): D("2300"), day(0): D("1700")},
    # 3 sessions a week since 5 days ago: covered days today-5 .. today = 6
    training_plan=ActivePlan(day(5), day(-50), sessions_per_week=3),
    # target 2000, from 4 days ago: 5 days, within 1800-2200 only today-4 (2000)
    diet_plan=ActivePlan(day(4), day(-50), daily_kcal=2000),
)


def test_windows():
    assert window("week", TODAY) == (day(6), TODAY)
    assert window("month", TODAY) == (day(29), TODAY)
    assert window("3months", TODAY) == (day(89), TODAY)


def test_minimum_history_is_7_distinct_days():
    assert not enough_history(6)
    assert enough_history(7)


def test_summary_of_a_hand_computed_week():
    s = summary("week", TODAY, record_days=7, data=DATA)

    assert (s.status, s.period_start, s.period_end) == ("ok", day(6), TODAY)
    assert s.weight_change == D("-0.6")  # 79.4 - 80.0
    assert s.total_workouts == 2
    assert s.avg_workouts_per_week == 2.0  # 2 / (7 / 7)
    assert s.avg_calories == pytest.approx(2000.0)  # (2000 + 2300 + 1700) / 3
    assert s.tonnage == D("1430")  # 600 + 480 + 350
    # 2 workouts / (3 x 6 / 7) x 100 = 77.78
    assert s.workout_compliance_pct == pytest.approx(2 / (3 * 6 / 7) * 100)
    # 5 days from the plan start, 1 within +/-10 % (2300 and 1700 are outside)
    assert s.diet_compliance_pct == pytest.approx(20.0)
    # exercise 11 has only bodyweight sets, so no e1RM: it is not a key lift
    assert [k.exercise_id for k in s.key_lifts] == [10]


def test_month_divides_by_its_weeks():
    s = summary("month", TODAY, record_days=7, data=DATA)
    assert s.avg_workouts_per_week == pytest.approx(2 / (30 / 7))


def test_insufficient_history_hides_everything():
    s = summary("week", TODAY, record_days=6, data=DATA)
    assert s.status == "insufficient_data"
    assert (s.total_workouts, s.tonnage, s.key_lifts) == (None, None, [])


def test_a_window_without_data_has_null_metrics():
    empty = AnalyticsData([], [], [], {}, DATA.training_plan, DATA.diet_plan)
    s = summary("week", TODAY, record_days=30, data=empty)
    assert s.status == "ok"
    assert (s.weight_change, s.total_workouts, s.avg_calories, s.tonnage) == (None,) * 4
    assert (s.workout_compliance_pct, s.diet_compliance_pct, s.key_lifts) == (None, None, [])


def test_compliance_is_null_without_an_active_plan():
    data = AnalyticsData(DATA.weigh_ins, DATA.workouts, DATA.sets, DATA.daily_kcal, None, None)
    s = summary("week", TODAY, record_days=7, data=data)
    assert (s.workout_compliance_pct, s.diet_compliance_pct) == (None, None)


def test_key_lifts_rank_by_workouts_then_sets_and_use_1_to_12_reps():
    sets = [
        row(1, 9, 1, 5, 100, name="Squat"),  # e1RM 116.67, first day of squat
        row(2, 5, 1, 3, 110, name="Squat"),  # e1RM 121
        row(1, 9, 2, 10, 60, name="Bench"),  # 80
        row(2, 5, 2, 15, 70, name="Bench"),  # 15 reps: not counted
        row(1, 9, 3, 8, 40, name="Row"),
        row(1, 9, 3, 8, 40, name="Row"),
        row(1, 9, 4, 8, 20, name="Curl"),
    ]
    lifts = key_lifts(sets)

    # Squat and Bench: 2 workouts; Squat first by id; Row: 1 workout, 2 sets > Curl
    assert [k.exercise_name for k in lifts] == ["Squat", "Bench", "Row"]
    squat, bench, _ = lifts
    assert (round(squat.first_e1rm, 2), round(squat.best_e1rm, 2)) == (D("116.67"), D("121.00"))
    assert (bench.first_e1rm, bench.best_e1rm) == (D("80"), D("80"))


def test_series():
    start, end = window("week", TODAY)
    assert series("weight", DATA, start, end) == [(day(6), 80.0), (day(2), 79.4)]
    assert series("tonnage", DATA, start, end) == [(day(5), 1080.0), (day(1), 350.0)]
    assert series("calories", DATA, start, end) == [
        (day(4), 2000.0),
        (day(3), 2300.0),
        (day(0), 1700.0),
    ]
    # ISO weeks dated Monday: 2026-10-05 (today-9) and 2026-10-12 (today-2)
    assert series("workouts_per_week", DATA, start, end) == [
        (date(2026, 10, 5), 1.0),
        (date(2026, 10, 12), 1.0),
    ]


def test_a_workout_day_without_weighted_sets_has_zero_tonnage():
    data = AnalyticsData([], [(3, day(0))], [row(3, 0, 11, 12, 0)], {}, None, None)
    start, end = window("week", TODAY)
    assert series("tonnage", data, start, end) == [(TODAY, 0.0)]
