"""Analytics metrics and chart series (algorithms.md sections 7 and 8; FR-R1 to FR-R3, FR-R5).

Pure functions over the rows DATA's queries return; windows are in the user's time
zone: `week` = today - 6 to today, `month` 30 days, `3months` 90 days.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.domain.compliance import diet_compliance, workout_compliance
from app.domain.constants import KEY_LIFTS, MIN_HISTORY_DAYS, PERIOD_DAYS, PR_MAX_REPS
from app.domain.records import e1rm


@dataclass(frozen=True)
class LoggedSetRow:
    workout_id: int
    log_date: date
    exercise_id: int
    exercise_name: str
    reps: int
    weight: Decimal
    completed: bool


@dataclass(frozen=True)
class ActivePlan:
    """The part of an active plan analytics needs."""

    start: date
    end: date
    sessions_per_week: int = 0  # training plan
    daily_kcal: int = 0  # diet plan


@dataclass(frozen=True)
class KeyLift:
    exercise_id: int
    exercise_name: str
    first_e1rm: Decimal
    best_e1rm: Decimal


@dataclass(frozen=True)
class Summary:
    status: str  # ok | insufficient_data
    period_start: date
    period_end: date
    weight_change: Decimal | None = None
    total_workouts: int | None = None
    avg_workouts_per_week: float | None = None
    avg_calories: float | None = None
    tonnage: Decimal | None = None
    workout_compliance_pct: float | None = None
    diet_compliance_pct: float | None = None
    key_lifts: list[KeyLift] = field(default_factory=list)


@dataclass(frozen=True)
class AnalyticsData:
    """Everything of one user one window needs."""

    weigh_ins: list[tuple[date, Decimal]]  # in the window, by date
    workouts: list[tuple[int, date]]  # live workouts in the window: (id, log date)
    sets: list[LoggedSetRow]  # of those workouts
    daily_kcal: dict[date, Decimal]  # logged kcal per day in the window
    training_plan: ActivePlan | None
    diet_plan: ActivePlan | None


def window(period: str, today: date) -> tuple[date, date]:
    return today - timedelta(days=PERIOD_DAYS[period] - 1), today


def enough_history(record_days: int) -> bool:
    """FR-R5: at least 7 distinct days with any record over the whole history."""
    return record_days >= MIN_HISTORY_DAYS


def _overlap(start: date, end: date, plan: ActivePlan) -> tuple[date, date] | None:
    first, last = max(start, plan.start), min(end, plan.end)
    return (first, last) if first <= last else None


def training_compliance(
    workouts: list[tuple[int, date]], plan: ActivePlan | None, start: date, end: date
) -> float | None:
    """Section 7: workouts in the covered part / (sessions per week x covered days / 7)."""
    if plan is None or (covered := _overlap(start, end, plan)) is None:
        return None
    first, last = covered
    done = sum(1 for _, day in workouts if first <= day <= last)
    return workout_compliance(done, plan.sessions_per_week, (last - first).days + 1)


def _diet_compliance(
    daily_kcal: dict[date, Decimal], plan: ActivePlan | None, start: date, end: date
) -> float | None:
    """Section 7: days from the plan start within +/-10 % / days; a day without logs fails."""
    if plan is None or (covered := _overlap(start, end, plan)) is None:
        return None
    first, last = covered
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return diet_compliance(days, daily_kcal, plan.daily_kcal)


def _counted(row: LoggedSetRow) -> bool:
    return row.completed and row.weight > 0


def key_lifts(sets: list[LoggedSetRow]) -> list[KeyLift]:
    """The three exercises with most workouts (then sets); first and best e1RM of their
    completed sets with weight and 1-12 reps. "First" is the best set of the earliest day."""
    workouts: dict[int, set[int]] = defaultdict(set)
    counts: dict[int, int] = defaultdict(int)
    names: dict[int, str] = {}
    for row in sets:
        workouts[row.exercise_id].add(row.workout_id)
        counts[row.exercise_id] += 1
        names[row.exercise_id] = row.exercise_name
    ranked = sorted(workouts, key=lambda e: (-len(workouts[e]), -counts[e], e))
    lifts = []
    for exercise_id in ranked:
        eligible = [
            r
            for r in sets
            if r.exercise_id == exercise_id and _counted(r) and 1 <= r.reps <= PR_MAX_REPS
        ]
        if not eligible:
            continue
        first_day = min(r.log_date for r in eligible)
        first = max(e1rm(r.weight, r.reps) for r in eligible if r.log_date == first_day)
        best = max(e1rm(r.weight, r.reps) for r in eligible)
        lifts.append(KeyLift(exercise_id, names[exercise_id], first, best))
        if len(lifts) == KEY_LIFTS:
            break
    return lifts


def summary(period: str, today: date, record_days: int, data: AnalyticsData) -> Summary:
    start, end = window(period, today)
    if not enough_history(record_days):
        return Summary("insufficient_data", start, end)
    if not (data.weigh_ins or data.workouts or data.daily_kcal):
        return Summary("ok", start, end)  # a window without data: null metrics
    days = PERIOD_DAYS[period]
    weights = [w for _, w in data.weigh_ins]
    total = len(data.workouts)
    return Summary(
        status="ok",
        period_start=start,
        period_end=end,
        weight_change=weights[-1] - weights[0] if len(weights) >= 2 else None,
        total_workouts=total,
        avg_workouts_per_week=total / (days / 7),
        avg_calories=(
            float(sum(data.daily_kcal.values()) / len(data.daily_kcal)) if data.daily_kcal else None
        ),
        tonnage=(
            sum((r.reps * r.weight for r in data.sets if _counted(r)), Decimal(0))
            if data.workouts
            else None
        ),
        workout_compliance_pct=training_compliance(data.workouts, data.training_plan, start, end),
        diet_compliance_pct=_diet_compliance(data.daily_kcal, data.diet_plan, start, end),
        key_lifts=key_lifts(data.sets),
    )


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def series(metric: str, data: AnalyticsData, start: date, end: date) -> list[tuple[date, float]]:
    """Weight per weigh-in, tonnage per workout day, calories per logged day, workouts per
    ISO week dated Monday."""
    if metric == "weight":
        return [(day, float(weight)) for day, weight in data.weigh_ins]
    if metric == "calories":
        return [(day, float(kcal)) for day, kcal in sorted(data.daily_kcal.items())]
    if metric == "tonnage":
        per_day: dict[date, Decimal] = defaultdict(Decimal)
        for day in {day for _, day in data.workouts}:
            per_day[day] += 0
        for row in data.sets:
            if _counted(row):
                per_day[row.log_date] += row.reps * row.weight
        return [(day, float(total)) for day, total in sorted(per_day.items())]
    weeks: dict[date, int] = {}
    monday = _monday(start)
    while monday <= end:
        weeks[monday] = 0
        monday += timedelta(days=7)
    for _, day in data.workouts:
        weeks[_monday(day)] += 1
    return sorted((day, float(count)) for day, count in weeks.items())
