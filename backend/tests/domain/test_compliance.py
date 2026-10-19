"""Compliance % (algorithms.md section 7)."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.domain.compliance import diet_compliance, workout_compliance


def test_workout_compliance():
    # 3 sessions per week over 14 days = 6 planned, 5 done
    assert workout_compliance(5, 3, 14) == pytest.approx(83.3333, rel=1e-4)


def test_workout_compliance_partial_week():
    # 4 per week over 10 days = 5.714 planned
    assert workout_compliance(4, 4, 10) == pytest.approx(70.0)


def test_workout_compliance_without_plan_overlap():
    assert workout_compliance(2, 3, 0) is None


def test_diet_compliance_counts_days_within_ten_percent():
    start = date(2026, 10, 1)
    days = [start + timedelta(days=i) for i in range(5)]
    logged = {
        days[0]: D("2000"),  # exact
        days[1]: D("2200"),  # +10 %, on the boundary
        days[2]: D("1799"),  # -10.05 %
        days[3]: D("2500"),
        # days[4] has no log
    }
    assert diet_compliance(days, logged, 2000) == pytest.approx(40.0)


def test_diet_compliance_empty_period():
    assert diet_compliance([], {}, 2000) is None
