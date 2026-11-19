"""Progress reports (B-25; FR-R1, FR-R5; api-rules.md "Reports and notifications").

A report stores the metrics of `algorithms.md` 8 over its period, rounded as the
analytics answers round them, so a report equals the analytics of the same period.
Period rules (8): Monday-Sunday is weekly, a calendar month is monthly, anything else
custom; at most 366 days and not after today.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.domain.analytics import AnalyticsData, period_summary, planned_sessions
from app.domain.constants import MAX_REPORT_DAYS, ReportType
from app.domain.prediction import GoalPrediction
from app.domain.rounding import round_half_up


@dataclass(frozen=True)
class ReportKeyLift:
    exercise_id: int
    exercise_name: str
    first_e1rm: Decimal
    best_e1rm: Decimal


@dataclass(frozen=True)
class ReportFigures:
    report_type: ReportType
    period_start: date
    period_end: date
    weight_difference: Decimal | None
    training_volume: Decimal
    training_sessions_completed: int
    training_sessions_planned: int
    workout_compliance_pct: Decimal | None
    diet_compliance_pct: Decimal | None
    avg_cals_daily: int | None
    key_lifts: tuple[ReportKeyLift, ...]
    estimated_goal_completion_date: date | None
    irregular_data: bool


def report_type(start: date, end: date) -> ReportType:
    if start.weekday() == 0 and end == start + timedelta(days=6):
        return ReportType.WEEKLY
    last_day = calendar.monthrange(start.year, start.month)[1]
    if start.day == 1 and end == start.replace(day=last_day):
        return ReportType.MONTHLY
    return ReportType.CUSTOM


def period_problems(start: date, end: date, today: date) -> list[dict]:
    """422 details of an invalid period (the Error model's `details`)."""
    problems = []
    if end < start:
        problems.append(
            {"field": "body.period_end", "code": "invalid_value", "message": "Before the start"}
        )
    elif (end - start).days + 1 > MAX_REPORT_DAYS:
        problems.append(
            {
                "field": "body.period_end",
                "code": "invalid_value",
                "message": f"A report covers at most {MAX_REPORT_DAYS} days",
            }
        )
    if end > today:
        problems.append(
            {"field": "body.period_end", "code": "future_date", "message": "After today"}
        )
    return problems


def _round(value, places: int) -> Decimal | None:
    return None if value is None else round_half_up(Decimal(str(value)), places)


def report_figures(
    start: date, end: date, data: AnalyticsData, prediction: GoalPrediction
) -> ReportFigures:
    """`data` covers the period; `prediction` is taken as of the generation day."""
    s = period_summary(start, end, data)
    planned = planned_sessions(data.training_plan, start, end)
    avg_cals = _round(s.avg_calories, 0)
    return ReportFigures(
        report_type=report_type(start, end),
        period_start=start,
        period_end=end,
        weight_difference=_round(s.weight_change, 2),
        training_volume=_round(s.tonnage, 1) or Decimal(0),
        training_sessions_completed=s.total_workouts or 0,
        # api-rules.md: the compliance denominator, rounded
        training_sessions_planned=0 if planned is None else int(_round(planned, 0)),
        workout_compliance_pct=_round(s.workout_compliance_pct, 1),
        diet_compliance_pct=_round(s.diet_compliance_pct, 1),
        avg_cals_daily=None if avg_cals is None else int(avg_cals),
        key_lifts=tuple(
            ReportKeyLift(
                k.exercise_id, k.exercise_name, _round(k.first_e1rm, 2), _round(k.best_e1rm, 2)
            )
            for k in s.key_lifts
        ),
        estimated_goal_completion_date=prediction.estimated_date,
        irregular_data=prediction.irregular_data,
    )
