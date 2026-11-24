"""Demo users for the analytics charts (FR-R1 to FR-R5; test data for M-18 and DB-12).

Creates local demo accounts `demo-<slug>@example.com`, one per persona in PERSONAS, each
with a different goal, start date and behaviour, so every chart of the Stats screen (week,
month, 3 months), the summary tiles and the goal prediction card can be seen in its normal,
edge and empty states. Each account gets a profile, a chain of 56-day training and diet plans
(the last one active and covering today, the earlier ones archived, no two overlapping),
weigh-ins, workouts linked to the session of the plan in force that day, and nutrition logs
with totals only (no food items; about 1 in 5 looks like a photo log). Meal and workout logs
live in PostgreSQL; MongoDB holds only the recognition buffer and is not touched.

Idempotent by replacement: in one transaction each selected persona's account (the app_user
with exactly that email, case-insensitive) is deleted, which cascades to everything it owns,
and created again. No other user is read, changed or deleted. The reference seed must be
loaded first; when a library exercise the personas use is missing, nothing is changed.

Deterministic: one random.Random per persona and stream (a CRC of the slug), and every date
an offset from today in Europe/Warsaw, so two runs on the same day give the same rows (ids
and client_uuid excepted). Today's values are the anchor: --weeks extends the history
backwards and leaves the current weight, lift weights, active plans and the last 28 days of
the prediction as they are. Inside those 28 days the weight noise has its own least-squares
line removed, so the fitted slope is the persona's trend whatever the weekday.

Run from backend/:
    uv run python -m app.db.demo_seed [--only SLUG ...] [--weeks N] [--password PW]
                                       [--today YYYY-MM-DD]
"""

import argparse
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from random import Random
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, delete, func, insert, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.enums import DifficultyLevel, EquipmentType, GoalType, MealType, PlanStatus, SexType
from app.db.models import (
    AppUser,
    BodyMetrics,
    DietPlan,
    Exercise,
    NutritionLog,
    SessionExercise,
    TrainingPlan,
    TrainingSession,
    UserProfile,
    WorkoutLog,
    WorkoutLogExercise,
    WorkoutSet,
)
from app.db.session import create_sync_engine
from app.domain.constants import PLAN_DURATION_DAYS, PREDICTION_WINDOW_DAYS

TIMEZONE = "Europe/Warsaw"
# example.com (RFC 2606) never reaches a real mailbox; the API's EmailStr refuses special-use
# domains such as .local and .test, so an account there could not log in.
EMAIL = "demo-{slug}@example.com"
DEFAULT_PASSWORD = "demo12345"  # local and demo databases only
MAX_WEEKS = 104

WEIGH_IN_WEEKDAYS = (0, 2, 5)  # Mon, Wed, Sat; plus a weigh-in today
PAL = Decimal("1.550")
TDEE = {SexType.MALE: 2750, SexType.FEMALE: 2150}
WEIGHT_STEP = Decimal("2.5")
MEAL_SHARES = {
    MealType.BREAKFAST: 0.25,
    MealType.LUNCH: 0.35,
    MealType.DINNER: 0.30,
    MealType.SNACK: 0.10,
}
MEAL_HOURS = {MealType.BREAKFAST: 8, MealType.LUNCH: 13, MealType.SNACK: 16, MealType.DINNER: 19}
PHOTO_LOG_SHARE = 0.2
INCOMPLETE_SET_SHARE = 0.06  # of workouts with one set not completed


@dataclass(frozen=True)
class Lift:
    """One exercise of a session template; `weight` in kg today, before the persona factor."""

    name: str
    weight: float
    main: bool = False  # progresses: lighter by the persona's step every progression period
    barbell: bool = False  # never lighter than the empty bar

    @property
    def bodyweight(self) -> bool:
        return self.weight == 0


# Squat, bench and deadlift are each in two of the first three sessions, so they are the
# key lifts (algorithms.md 8: most workouts) of every gym persona.
GYM_SESSIONS: list[list[Lift]] = [
    [
        Lift("Barbell back squat", 100, main=True, barbell=True),
        Lift("Barbell bench press", 80, main=True, barbell=True),
        Lift("Barbell row", 70, barbell=True),
        Lift("Dumbbell curl", 14),
    ],
    [
        Lift("Barbell deadlift", 130, main=True, barbell=True),
        Lift("Barbell overhead press", 50, barbell=True),
        Lift("Lat pulldown", 60),
        Lift("Bulgarian split squat", 20),
        Lift("Face pull", 20),
    ],
    [
        Lift("Barbell bench press", 80, main=True, barbell=True),
        Lift("Barbell back squat", 100, main=True, barbell=True),
        Lift("Seated cable row", 60),
        Lift("Barbell deadlift", 130, main=True, barbell=True),
        Lift("Overhead dumbbell extension", 18),
    ],
    [
        Lift("Barbell deadlift", 130, main=True, barbell=True),
        Lift("Incline dumbbell press", 26),
        Lift("One-arm dumbbell row", 30),
        Lift("Dumbbell step-up", 16),
    ],
]
HOME_SESSION = [
    Lift("Push-up", 0),
    Lift("Reverse lunge", 0),
    Lift("Inverted row under a table", 0),
    Lift("Goblet squat", 12, main=True),
]
SESSION_NAMES = ("Full body A", "Full body B", "Full body C", "Full body D")


@dataclass(frozen=True)
class Persona:
    slug: str
    goal: GoalType
    sex: SexType
    age: int
    height: int
    start_weight: float  # kg at the start of the default history
    weekly_change: float  # kg per week, the trend
    noise: float  # weigh-ins scatter uniformly by up to this many kg around the trend
    target: float | None
    training_weekdays: tuple[int, ...]  # Mon = 0; one session per day
    workout_compliance: float  # share of planned workouts done
    diet_kcal: int
    logged_share: float  # share of days with nutrition logs
    kcal_spread: float  # a logged day's total is the goal x (1 +/- up to this)
    history_weeks: int | None = None  # whole weeks of history; --weeks replaces it
    history_days: int | None = None  # a short fixed history that --weeks leaves alone
    experience: DifficultyLevel = DifficultyLevel.INTERMEDIATE
    equipment: EquipmentType = EquipmentType.GYM
    lift_factor: float = 1.0  # times the template weights
    sets: int = 3
    reps: tuple[int, int] = (6, 12)
    progression_kg: float = 2.5
    progression_days: int = 14
    block_workouts: dict[int, int] = field(default_factory=dict)  # 7-day block -> workouts
    weigh_in_gap: tuple[int, int] | None = None  # days-ago range without weigh-ins
    weigh_in_days: tuple[int, ...] | None = None  # days ago; replaces the weekly schedule
    meal_days: tuple[int, ...] | None = None  # days ago; replaces logged_share

    @property
    def email(self) -> str:
        return EMAIL.format(slug=self.slug)

    @property
    def days_per_week(self) -> int:
        return len(self.training_weekdays)


PERSONAS: list[Persona] = [
    Persona(  # steady loss: prediction ok with a date, no warnings
        slug="loss",
        goal=GoalType.WEIGHT_LOSS,
        sex=SexType.MALE,
        age=28,
        height=180,
        start_weight=88.0,
        weekly_change=-0.45,
        noise=0.3,
        target=80.0,
        training_weekdays=(0, 2, 4),
        workout_compliance=0.85,
        diet_kcal=2250,
        logged_share=0.9,
        kcal_spread=0.15,
        history_weeks=13,
        block_workouts={2: 3, 5: 1},  # a perfect week and a weak week
    ),
    Persona(  # surplus and slow gain: prediction ok, upward trend
        slug="gain",
        goal=GoalType.MUSCLE_GAIN,
        sex=SexType.FEMALE,
        age=24,
        height=165,
        start_weight=58.0,
        weekly_change=0.25,
        noise=0.2,
        target=63.0,
        training_weekdays=(0, 1, 3, 4),
        workout_compliance=0.9,
        diet_kcal=2400,
        logged_share=0.9,
        kcal_spread=0.10,
        history_weeks=8,
        lift_factor=0.55,
    ),
    Persona(  # heavy and long: no target, 3 months full, the highest tonnage
        slug="strength",
        goal=GoalType.STRENGTH,
        sex=SexType.MALE,
        age=35,
        height=185,
        start_weight=92.0,
        weekly_change=0.0,
        noise=0.5,
        target=None,
        training_weekdays=(0, 1, 3, 5),
        workout_compliance=0.8,
        diet_kcal=3000,
        logged_share=0.85,
        kcal_spread=0.12,
        history_weeks=26,
        lift_factor=1.4,
        sets=5,
        reps=(3, 6),
    ),
    Persona(  # scattered weight, a gap, half the workouts: ok with three warnings
        slug="irregular",
        goal=GoalType.WEIGHT_LOSS,
        sex=SexType.FEMALE,
        age=41,
        height=170,
        start_weight=79.0,
        weekly_change=-0.25,
        noise=1.2,
        target=70.0,
        training_weekdays=(0, 2, 4),
        workout_compliance=0.5,
        diet_kcal=1900,
        logged_share=0.6,
        kcal_spread=0.30,
        history_weeks=10,
        lift_factor=0.5,
        block_workouts={0: 1, 1: 2, 2: 0, 3: 2, 4: 3, 5: 1, 6: 0, 7: 2, 8: 3, 9: 1},
        weigh_in_gap=(9, 20),  # 12 days without a weigh-in inside the last 28
    ),
    Persona(  # 9 days, just enough records: charts ok, prediction insufficient_data
        slug="newbie",
        goal=GoalType.GENERAL_FITNESS,
        sex=SexType.MALE,
        age=19,
        height=175,
        start_weight=75.0,
        weekly_change=-0.2,
        noise=0.2,
        target=72.0,
        training_weekdays=(0, 2, 4),
        workout_compliance=1.0,
        diet_kcal=2600,
        logged_share=1.0,
        kcal_spread=0.10,
        history_days=9,
        experience=DifficultyLevel.BEGINNER,
        equipment=EquipmentType.HOME,
        progression_kg=2.0,
        progression_days=3,  # Goblet squat 8 to 12 kg
        block_workouts={1: 0},  # 3 workouts, all in the last 7 days
        weigh_in_days=(6, 3, 0),  # span 6 days < 7
        meal_days=(8, 7, 5, 4, 2, 1),
    ),
    Persona(  # 2 days: every chart and the summary insufficient_data
        slug="fresh",
        goal=GoalType.MAINTENANCE,
        sex=SexType.FEMALE,
        age=30,
        height=168,
        start_weight=62.0,
        weekly_change=0.0,
        noise=0.2,
        target=62.0,
        training_weekdays=(0, 2, 4),
        workout_compliance=0.0,
        diet_kcal=2150,
        logged_share=1.0,
        kcal_spread=0.10,
        history_days=2,
        lift_factor=0.5,
        weigh_in_days=(1, 0),
        meal_days=(1, 0),
    ),
]
PERSONAS_BY_SLUG = {p.slug: p for p in PERSONAS}


class DemoSeedError(Exception):
    pass


# ---------------------------------------------------------------- generated rows


@dataclass
class SessionRows:
    session: dict[str, Any]
    exercises: list[dict[str, Any]]  # `exercise` is the library name


@dataclass
class TrainingPlanRows:
    plan: dict[str, Any]
    sessions: list[SessionRows]


@dataclass
class LoggedExerciseRows:
    exercise: str
    sort_order: int
    sets: list[dict[str, Any]]


@dataclass
class WorkoutRows:
    log: dict[str, Any]
    plan_index: int | None  # into DemoRows.training_plans; None before the first plan
    session_order: int | None
    exercises: list[LoggedExerciseRows]


@dataclass
class DemoRows:
    """Plain rows of one persona; ids and user_id are filled in by `write`."""

    persona: Persona
    start: date  # first day of the history = registration_date
    user: dict[str, Any]
    profile: dict[str, Any]
    training_plans: list[TrainingPlanRows]
    diet_plans: list[dict[str, Any]]
    weigh_ins: list[dict[str, Any]]
    workouts: list[WorkoutRows]
    nutrition_logs: list[dict[str, Any]]

    def counts(self) -> Counter[str]:
        sessions = [s for p in self.training_plans for s in p.sessions]
        logged = [e for w in self.workouts for e in w.exercises]
        return Counter(
            {
                "app_user": 1,
                "user_profile": 1,
                "training_plan": len(self.training_plans),
                "training_session": len(sessions),
                "session_exercise": sum(len(s.exercises) for s in sessions),
                "diet_plan": len(self.diet_plans),
                "body_metrics": len(self.weigh_ins),
                "workout_log": len(self.workouts),
                "workout_log_exercise": len(logged),
                "workout_set": sum(len(e.sets) for e in logged),
                "nutrition_log": len(self.nutrition_logs),
            }
        )

    def exercise_names(self) -> set[str]:
        planned = {
            e["exercise"] for p in self.training_plans for s in p.sessions for e in s.exercises
        }
        return planned | {e.exercise for w in self.workouts for e in w.exercises}


def history_length(persona: Persona, weeks: int | None = None) -> int:
    """Days of history including today."""
    if persona.history_weeks is None:
        assert persona.history_days is not None
        return persona.history_days
    return 7 * (weeks or persona.history_weeks)


def stream(persona: Persona, name: str) -> Random:
    """A random stream of its own per persona and purpose: changing one leaves the others."""
    return Random(zlib.crc32(f"{persona.slug}:{name}".encode()))


def _kg(value: float, places: str = "0.1") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(TIMEZONE))


def plan_periods(start: date, today: date) -> list[tuple[date, date]]:
    """56-day plans, oldest first: the last one active and covering today (as long a part of
    the last 28 days as possible), the earlier ones each ending the day before the next
    starts. Days before the first plan that do not fit a whole plan have none."""
    first = max(start, today - timedelta(days=PLAN_DURATION_DAYS - 1))
    periods = [(first, first + timedelta(days=PLAN_DURATION_DAYS))]
    while (earlier := periods[0][0] - timedelta(days=PLAN_DURATION_DAYS + 1)) >= start:
        periods.insert(0, (earlier, earlier + timedelta(days=PLAN_DURATION_DAYS)))
    return periods


def _plan_index(periods: list[tuple[date, date]], day: date) -> int | None:
    return next((i for i, (s, e) in enumerate(periods) if s <= day <= e), None)


def _detrended(xs: list[float], noise: list[float]) -> list[float]:
    """`noise` minus its own least-squares line over `xs`: mean 0, no slope."""
    n = len(xs)
    if n < 2:
        return noise
    mean_x, mean_n = sum(xs) / n, sum(noise) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    slope = (
        0.0
        if sxx == 0
        else sum((x - mean_x) * (v - mean_n) for x, v in zip(xs, noise, strict=True)) / sxx
    )
    return [v - mean_n - slope * (x - mean_x) for x, v in zip(xs, noise, strict=True)]


def weigh_ins(persona: Persona, today: date, days: int) -> list[tuple[date, Decimal]]:
    """Trend anchored at today plus noise; inside the last 28 days the noise is detrended."""
    rng = stream(persona, "weight")
    per_day = persona.weekly_change / 7
    trend_today = persona.start_weight + per_day * (history_length(persona) - 1)
    if persona.weigh_in_days is not None:
        days_ago = sorted(k for k in persona.weigh_in_days if k < days)
    else:
        gap = persona.weigh_in_gap
        days_ago = [
            k
            for k in range(days)
            if ((today - timedelta(days=k)).weekday() in WEIGH_IN_WEEKDAYS or k == 0)
            and not (gap and gap[0] <= k <= gap[1])
        ]
    noise = {k: rng.uniform(-persona.noise, persona.noise) for k in days_ago}
    recent = [k for k in days_ago if k < PREDICTION_WINDOW_DAYS]
    noise.update(
        zip(recent, _detrended([-k for k in recent], [noise[k] for k in recent]), strict=True)
    )
    return sorted(
        (today - timedelta(days=k), _kg(trend_today - per_day * k + noise[k])) for k in days_ago
    )


def block_counts(persona: Persona, today: date, days: int) -> list[list[int]]:
    """Days ago of the workouts done, per 7-day block counted back from today (block 0 =
    today and the 6 days before). Each whole block holds every weekday once, so it has
    exactly days_per_week planned days; the counts follow `workout_compliance` by error
    diffusion from today backwards, with `block_workouts` overriding single blocks."""
    rng = stream(persona, "workouts")
    blocks, error = [], 0.0
    for b in range((days + 6) // 7):
        planned = [
            k
            for k in range(7 * b, min(7 * b + 7, days))
            if (today - timedelta(days=k)).weekday() in persona.training_weekdays
        ]
        if b in persona.block_workouts:
            done = min(persona.block_workouts[b], len(planned))
        else:
            wanted = persona.workout_compliance * len(planned) + error
            done = min(len(planned), max(0, int(wanted + 0.5)))
            error = wanted - done
        blocks.append(sorted(rng.sample(planned, done)))
    return blocks


def _lift_weight(persona: Persona, lift: Lift, days_ago: int) -> Decimal:
    if lift.bodyweight:
        return Decimal(0)
    if persona.equipment == EquipmentType.GYM:
        today_kg = float(_kg(lift.weight * persona.lift_factor / 2.5, "1")) * 2.5
    else:
        today_kg = lift.weight
    if lift.main:
        today_kg -= persona.progression_kg * (days_ago // persona.progression_days)
    lowest = 20.0 if lift.barbell else (8.0 if persona.equipment == EquipmentType.HOME else 2.5)
    return _kg(max(today_kg, lowest), "0.01")


def _templates(persona: Persona) -> list[list[Lift]]:
    if persona.equipment == EquipmentType.GYM:
        return GYM_SESSIONS[: persona.days_per_week]
    return [HOME_SESSION] * persona.days_per_week


def training_plans(
    persona: Persona, today: date, periods: list[tuple[date, date]]
) -> list[TrainingPlanRows]:
    """One plan per period; planned_weight is the lift's weight on the plan's first day."""
    plans = []
    for i, (start, end) in enumerate(periods):
        days_ago = (today - start).days
        active = i == len(periods) - 1
        sessions = []
        for order, (weekday, lifts) in enumerate(
            zip(persona.training_weekdays, _templates(persona), strict=True), start=1
        ):
            sessions.append(
                SessionRows(
                    session={
                        "session_order": order,
                        "session_name": SESSION_NAMES[order - 1],
                        "day_of_week": weekday + 1,  # 1 = Monday (ISO)
                        "estimated_duration": 40 if persona.equipment == EquipmentType.HOME else 60,
                    },
                    exercises=[
                        {
                            "exercise": lift.name,
                            "sort_order": n,
                            "planned_sets": persona.sets,
                            "planned_reps": persona.reps[1],
                            "planned_weight": None
                            if lift.bodyweight
                            else _lift_weight(persona, lift, days_ago),
                            "rest_seconds": 180 if persona.reps[1] <= 6 else 90,
                        }
                        for n, lift in enumerate(lifts, start=1)
                    ],
                )
            )
        plans.append(
            TrainingPlanRows(
                plan={
                    "plan_name": f"Full body {persona.days_per_week} days",
                    "goal": persona.goal,
                    "num_training_days": persona.days_per_week,
                    "experience_level": persona.experience,
                    "equipment": persona.equipment,
                    "generated_at": _at(start, 9),
                    "start_date": start,
                    "end_date": end,
                    "status": PlanStatus.ACTIVE if active else PlanStatus.ARCHIVED,
                },
                sessions=sessions,
            )
        )
    return plans


def workouts(
    persona: Persona, today: date, days: int, periods: list[tuple[date, date]]
) -> list[WorkoutRows]:
    rng = stream(persona, "sets")
    templates = dict(zip(persona.training_weekdays, _templates(persona), strict=True))
    orders = {weekday: n for n, weekday in enumerate(persona.training_weekdays, start=1)}
    low, high = persona.reps
    rows = []
    for block in block_counts(persona, today, days):
        for k in block:
            day = today - timedelta(days=k)
            weekday = day.weekday()
            plan_index = _plan_index(periods, day)
            incomplete = rng.random() < INCOMPLETE_SET_SHARE
            lifts = templates[weekday]
            failing = rng.randrange(len(lifts))
            exercises = []
            for n, lift in enumerate(lifts, start=1):
                reps = rng.randint(low, high)
                weight = _lift_weight(persona, lift, k)
                sets = []
                for s in range(1, persona.sets + 1):
                    done = not (incomplete and n - 1 == failing and s == persona.sets)
                    sets.append(
                        {
                            "set_number": s,
                            "reps": reps if done else max(reps - 3, 0),
                            "weight": weight,
                            "completed": done,
                            "rpe": rng.randint(6, 8),
                        }
                    )
                exercises.append(LoggedExerciseRows(lift.name, n, sets))
            rows.append(
                WorkoutRows(
                    log={
                        "log_date": day,
                        "rpe_rating": rng.randint(6, 8),
                        "logged_at": _at(day, 18),
                    },
                    plan_index=plan_index,
                    session_order=None if plan_index is None else orders[weekday],
                    exercises=exercises,
                )
            )
    return sorted(rows, key=lambda w: w.log["log_date"])


def _macros(kcal: float, protein_share: float, fat_share: float) -> dict[str, Decimal]:
    """Grams whose 4/9/4 kcal add up to `kcal` (to rounding)."""
    protein = _kg(kcal * protein_share / 4, "0.01")
    fat = _kg(kcal * fat_share / 9, "0.01")
    carbs = _kg(max(kcal - 4 * float(protein) - 9 * float(fat), 0) / 4, "0.01")
    return {"protein": protein, "fat": fat, "carbs": carbs}


def diet_plans(persona: Persona, periods: list[tuple[date, date]]) -> list[dict[str, Any]]:
    goals = _macros(persona.diet_kcal, 0.25, 0.30)
    return [
        {
            "name": f"Diet {persona.diet_kcal} kcal",
            "goal": persona.goal,
            "meals_per_day": 4,
            "generated_at": _at(start, 9),
            "start_date": start,
            "end_date": end,
            "daily_cal_goal": persona.diet_kcal,
            "protein_goal": goals["protein"],
            "fat_goal": goals["fat"],
            "carbs_goal": goals["carbs"],
            "status": PlanStatus.ACTIVE if i == len(periods) - 1 else PlanStatus.ARCHIVED,
        }
        for i, (start, end) in enumerate(periods)
    ]


def nutrition_logs(persona: Persona, today: date, days: int) -> list[dict[str, Any]]:
    """Days and totals are drawn from today backwards, so they do not depend on the weekday
    or on --weeks."""
    rng = stream(persona, "diet")
    rows = []
    for k in range(days):
        logged = rng.random() < persona.logged_share
        if persona.meal_days is not None:
            logged = k in persona.meal_days
        total = persona.diet_kcal * (1 + rng.uniform(-persona.kcal_spread, persona.kcal_spread))
        meals = list(MEAL_SHARES) if rng.random() < 0.5 else list(MEAL_SHARES)[:3]
        weights = [MEAL_SHARES[m] * rng.uniform(0.9, 1.1) for m in meals]
        draws = [
            (
                rng.uniform(0.2, 0.3),
                rng.uniform(0.25, 0.35),
                rng.random(),
                rng.uniform(0.70, 0.95),
                rng.random() < 0.5,
            )
            for _ in meals
        ]
        if not logged:
            continue
        day = today - timedelta(days=k)
        for meal, weight, draw in zip(meals, weights, draws, strict=True):
            protein, fat, photo, confidence, edited = draw
            kcal = total * weight / sum(weights)
            grams = _macros(kcal, protein, fat)
            is_photo = photo < PHOTO_LOG_SHARE
            rows.append(
                {
                    "log_date": day,
                    "meal_type": meal,
                    "actual_cals": _kg(kcal, "0.01"),
                    "actual_protein": grams["protein"],
                    "actual_fat": grams["fat"],
                    "actual_carbs": grams["carbs"],
                    "ai_confidence": _kg(confidence, "0.01") if is_photo else None,
                    "ai_was_edited": edited if is_photo else None,
                    "logged_at": _at(day, MEAL_HOURS[meal]),
                }
            )
    return sorted(rows, key=lambda r: (r["log_date"], MEAL_HOURS[r["meal_type"]]))


def generate(persona: Persona, today: date, weeks: int | None = None) -> DemoRows:
    """Every row of one persona, without ids; pure."""
    days = history_length(persona, weeks)
    start = today - timedelta(days=days - 1)
    periods = plan_periods(start, today)
    weights = weigh_ins(persona, today, days)
    plans = training_plans(persona, today, periods)
    return DemoRows(
        persona=persona,
        start=start,
        user={
            "email": persona.email,
            "name": "Demo",
            "surname": persona.slug.capitalize(),
            "timezone": TIMEZONE,
            "registration_date": start,
        },
        profile={
            "age": persona.age,
            "sex": persona.sex,
            "current_weight": weights[-1][1] if weights else _kg(persona.start_weight),
            "height": persona.height,
            "activity_level_pal": PAL,
            "goal": persona.goal,
            "experience_level": persona.experience,
            "equipment": persona.equipment,
            "target_value": None if persona.target is None else _kg(persona.target),
            "tdee": TDEE[persona.sex],
            "profile_update": _at(start, 9),
        },
        training_plans=plans,
        diet_plans=diet_plans(persona, periods),
        weigh_ins=[
            {"measured_on": day, "weight": weight, "recorded_at": _at(day, 7, 30)}
            for day, weight in weights
        ],
        workouts=workouts(persona, today, days, periods),
        nutrition_logs=nutrition_logs(persona, today, days),
    )


# ---------------------------------------------------------------- writing


def _insert_many(conn: Connection, model: Any, rows: list[dict[str, Any]]) -> list[int]:
    """Bulk insert returning the new ids in the order of `rows`."""
    if not rows:
        return []
    statement = insert(model).returning(model.id, sort_by_parameter_order=True)
    return list(conn.execute(statement, rows).scalars())


def library_exercise_ids(conn: Connection, names: set[str]) -> dict[str, int]:
    """Ids of library exercises (user_id NULL) by name; a DemoSeedError names any missing."""
    found = dict(
        conn.execute(
            select(Exercise.name, Exercise.id).where(
                Exercise.user_id.is_(None), Exercise.name.in_(names)
            )
        ).all()
    )
    if missing := sorted(names - found.keys()):
        raise DemoSeedError(
            f"library exercises missing: {', '.join(missing)}; load the reference seed first "
            "(uv run python -m app.db.seed)"
        )
    return found


def write(
    conn: Connection, rows: DemoRows, password_hash: str, exercise_ids: dict[str, int]
) -> int:
    """Replace the persona's account by `rows` inside the caller's transaction; the new id."""
    conn.execute(delete(AppUser).where(func.lower(AppUser.email) == rows.user["email"].lower()))
    user_id = conn.execute(
        insert(AppUser).values(**rows.user, password_hash=password_hash).returning(AppUser.id)
    ).scalar_one()
    owned = {"user_id": user_id}
    conn.execute(insert(UserProfile).values(**rows.profile, **owned))

    plan_ids = _insert_many(conn, TrainingPlan, [p.plan | owned for p in rows.training_plans])
    session_keys = [
        (i, s.session["session_order"])
        for i, p in enumerate(rows.training_plans)
        for s in p.sessions
    ]
    session_ids = dict(
        zip(
            session_keys,
            _insert_many(
                conn,
                TrainingSession,
                [
                    s.session | {"training_plan_id": plan_ids[i]}
                    for i, p in enumerate(rows.training_plans)
                    for s in p.sessions
                ],
            ),
            strict=True,
        )
    )
    planned = [
        (i, s.session["session_order"], e)
        for i, p in enumerate(rows.training_plans)
        for s in p.sessions
        for e in s.exercises
    ]
    planned_ids = _insert_many(
        conn,
        SessionExercise,
        [
            {k: v for k, v in e.items() if k != "exercise"}
            | {
                "training_session_id": session_ids[(i, order)],
                "exercise_id": exercise_ids[e["exercise"]],
            }
            for i, order, e in planned
        ],
    )
    planned_by_key = {
        (i, order, e["sort_order"]): pid
        for (i, order, e), pid in zip(planned, planned_ids, strict=True)
    }

    _insert_many(conn, DietPlan, [p | owned for p in rows.diet_plans])
    _insert_many(conn, BodyMetrics, [w | owned for w in rows.weigh_ins])
    _insert_many(conn, NutritionLog, [n | owned for n in rows.nutrition_logs])

    log_ids = _insert_many(
        conn,
        WorkoutLog,
        [
            w.log
            | owned
            | {
                "training_session_id": None
                if w.plan_index is None
                else session_ids[(w.plan_index, w.session_order)]
            }
            for w in rows.workouts
        ],
    )
    logged = [
        (w, log_id, e)
        for w, log_id in zip(rows.workouts, log_ids, strict=True)
        for e in w.exercises
    ]
    logged_ids = _insert_many(
        conn,
        WorkoutLogExercise,
        [
            {
                "workout_log_id": log_id,
                "exercise_id": exercise_ids[e.exercise],
                "session_exercise_id": None
                if w.plan_index is None
                else planned_by_key.get((w.plan_index, w.session_order, e.sort_order)),
                "sort_order": e.sort_order,
            }
            for w, log_id, e in logged
        ],
    )
    _insert_many(
        conn,
        WorkoutSet,
        [
            s | {"workout_log_exercise_id": logged_id}
            for (_, _, e), logged_id in zip(logged, logged_ids, strict=True)
            for s in e.sets
        ],
    )
    return user_id


@dataclass(frozen=True)
class SeedResult:
    email: str
    user_id: int
    counts: Counter[str]


def seed(
    conn: Connection,
    personas: list[Persona],
    today: date,
    weeks: int | None = None,
    password: str = DEFAULT_PASSWORD,
    bcrypt_rounds: int | None = None,
) -> list[SeedResult]:
    """Replace the demo accounts of `personas` inside the caller's transaction."""
    generated = [generate(p, today, weeks) for p in personas]
    exercise_ids = library_exercise_ids(conn, set().union(*(g.exercise_names() for g in generated)))
    rounds = get_settings().bcrypt_rounds if bcrypt_rounds is None else bcrypt_rounds
    results = []
    for rows in generated:
        user_id = write(conn, rows, hash_password(password, rounds), exercise_ids)
        results.append(SeedResult(rows.persona.email, user_id, rows.counts()))
    return results


def _weeks(raw: str) -> int:
    value = int(raw)
    if not 1 <= value <= MAX_WEEKS:
        raise argparse.ArgumentTypeError(f"must be 1 to {MAX_WEEKS}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or recreate the local demo users.")
    parser.add_argument(
        "--only", nargs="+", choices=list(PERSONAS_BY_SLUG), metavar="SLUG", help="personas"
    )
    parser.add_argument("--weeks", type=_weeks, help="history of the personas that have one")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="shared password")
    parser.add_argument("--today", type=date.fromisoformat, help="YYYY-MM-DD, default today")
    args = parser.parse_args(argv)

    today = args.today or datetime.now(ZoneInfo(TIMEZONE)).date()
    personas = [PERSONAS_BY_SLUG[s] for s in args.only] if args.only else PERSONAS
    engine = create_sync_engine()
    try:
        with engine.begin() as conn:
            results = seed(conn, personas, today, args.weeks, args.password)
    except (DemoSeedError, ValueError) as error:
        print(f"demo seed error: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(f"today {today}, password for every account: {args.password}")
    for r in results:
        counts = "  ".join(f"{table} {n}" for table, n in r.counts.items() if table != "app_user")
        print(f"{r.email:<32} id {r.user_id:>5}  {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
