"""SqlAnalyticsStore on PostgreSQL (DB-10; algorithms.md 7 and 8, FR-R1 to FR-R3, FR-R5).

Calls the repository directly, below the endpoints of test_analytics_queries.py. Dates are
relative to today in Europe/Warsaw; every expected value is hand-computed in a comment.
Skipped without PostgreSQL.
"""

import functools
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.analytics import SqlAnalyticsUnitOfWork
from app.db.session import database_url
from app.domain.analytics import (
    ActivePlan,
    AnalyticsData,
    LoggedSetRow,
    enough_history,
    summary,
    window,
)
from app.domain.compliance import diet_compliance, workout_compliance
from tests.clock import today
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio

TODAY = today()
BENCH, PUSH_UP, SQUAT, DEADLIFT, CURL = 10, 11, 12, 13, 14
PLAN_DAYS = timedelta(days=56)


def day(n: int) -> date:
    return TODAY - timedelta(days=n)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


def _sql(statement: str, **params):
    with _sync_engine().begin() as db:
        return db.execute(text(statement), params)


@pytest.fixture
async def analytics(migrated_db) -> AsyncIterator[SqlAnalyticsUnitOfWork]:  # noqa: F811
    _sql("TRUNCATE app_user, exercise, muscle_group RESTART IDENTITY CASCADE")
    _sql(
        "INSERT INTO exercise (id, name, difficulty_level, equipment, is_compound, description,"
        " instruction) VALUES (10, 'Bench press', 'beginner', 'gym', true, '', ''),"
        " (11, 'Push-up', 'beginner', 'none', true, '', ''),"
        " (12, 'Back squat', 'beginner', 'gym', true, '', ''),"
        " (13, 'Deadlift', 'beginner', 'gym', true, '', ''),"
        " (14, 'Biceps curl', 'beginner', 'home', false, '', '')"
    )
    engine = create_async_engine(database_url().set(database=TEST_DB))
    yield SqlAnalyticsUnitOfWork(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


# ------------------------------------------------------------------ rows


def _user(email: str) -> int:
    return _sql(
        "INSERT INTO app_user (email, name, surname) VALUES (:e, 'A', 'B') RETURNING id", e=email
    ).scalar_one()


def _weigh_in(user: int, when: date, weight, deleted: bool = False) -> None:
    _sql(
        "INSERT INTO body_metrics (user_id, measured_on, weight, deleted_at)"
        " VALUES (:u, :d, :w, CASE WHEN :x THEN now() END)",
        u=user,
        d=when,
        w=weight,
        x=deleted,
    )


def _workout(
    user: int,
    when: date,
    sets: Sequence[tuple[int, int, float, bool]] = (),
    deleted: bool = False,
) -> int:
    """sets: (exercise id, reps, weight, completed), grouped per exercise in order."""
    log = _sql(
        "INSERT INTO workout_log (user_id, log_date, rpe_rating, deleted_at)"
        " VALUES (:u, :d, 7, CASE WHEN :x THEN now() END) RETURNING id",
        u=user,
        d=when,
        x=deleted,
    ).scalar_one()
    for order, exercise in enumerate(dict.fromkeys(s[0] for s in sets), start=1):
        logged = _sql(
            "INSERT INTO workout_log_exercise (workout_log_id, exercise_id, sort_order)"
            " VALUES (:l, :e, :o) RETURNING id",
            l=log,
            e=exercise,
            o=order,
        ).scalar_one()
        for number, (_, reps, weight, done) in enumerate(
            (s for s in sets if s[0] == exercise), start=1
        ):
            _sql(
                "INSERT INTO workout_set (workout_log_exercise_id, set_number, reps, weight,"
                " completed) VALUES (:x, :n, :r, :w, :c)",
                x=logged,
                n=number,
                r=reps,
                w=weight,
                c=done,
            )
    return log


def _kcal(user: int, when: date, kcal, deleted: bool = False) -> None:
    _sql(
        "INSERT INTO nutrition_log (user_id, log_date, meal_type, actual_cals, actual_protein,"
        " actual_fat, actual_carbs, deleted_at)"
        " VALUES (:u, :d, 'lunch', :k, 0, 0, 0, CASE WHEN :x THEN now() END)",
        u=user,
        d=when,
        k=kcal,
        x=deleted,
    )


def _training_plan(user: int, status: str, sessions: int, start: date | None = None) -> None:
    """A draft has no dates; active and archived plans run 56 days from `start`."""
    _sql(
        "INSERT INTO training_plan (user_id, plan_name, goal, num_training_days,"
        " experience_level, equipment, status, start_date, end_date)"
        " VALUES (:u, 'P', 'strength', :n, 'beginner', 'gym', :st, :s, :e)",
        u=user,
        n=sessions,
        st=status,
        s=start,
        e=None if start is None else start + PLAN_DAYS,
    )


def _diet_plan(user: int, status: str, kcal: int, start: date | None = None) -> None:
    _sql(
        "INSERT INTO diet_plan (user_id, name, goal, meals_per_day, daily_cal_goal, protein_goal,"
        " fat_goal, carbs_goal, status, start_date, end_date)"
        " VALUES (:u, 'D', 'maintenance', 3, :k, 100, 60, 250, :st, :s, :e)",
        u=user,
        k=kcal,
        st=status,
        s=start,
        e=None if start is None else start + PLAN_DAYS,
    )


def _profile(user: int, target) -> None:
    _sql(
        "INSERT INTO user_profile (user_id, age, sex, current_weight, height,"
        " activity_level_pal, goal, experience_level, equipment, target_value, tdee)"
        " VALUES (:u, 30, 'male', 90, 180, 1.55, 'weight_loss', 'beginner', 'gym', :t, 2800)",
        u=user,
        t=target,
    )


async def _record_days(analytics: SqlAnalyticsUnitOfWork, user: int) -> int:
    async with analytics() as store:
        return await store.record_days(user)


async def _data(
    analytics: SqlAnalyticsUnitOfWork, user: int, start: date, end: date
) -> AnalyticsData:
    async with analytics() as store:
        return await store.data(user, start, end)


# ------------------------------------------------------------------ a) record_days


async def test_record_days_counts_a_date_once_and_only_the_users_live_rows(analytics):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    # one date in all three tables
    _weigh_in(ann, day(3), 80)
    _workout(ann, day(3))
    _kcal(ann, day(3), 2000)
    # soft-deleted rows on three other dates
    _weigh_in(ann, day(5), 80, deleted=True)
    _workout(ann, day(6), [(BENCH, 5, 60, True)], deleted=True)
    _kcal(ann, day(7), 2000, deleted=True)
    # Bob's rows on three more dates
    _weigh_in(bob, day(8), 90)
    _workout(bob, day(9))
    _kcal(bob, day(10), 2500)

    assert await _record_days(analytics, ann) == 1  # day 3 only; days 5-7 deleted, 8-10 Bob's
    assert await _record_days(analytics, bob) == 3  # days 8, 9, 10


# ------------------------------------------------------------------ b) 6/7-day boundary


@pytest.mark.parametrize("seventh", ["weigh_in", "workout", "nutrition_log"])
async def test_six_days_over_three_tables_are_insufficient_and_a_seventh_is_enough(
    analytics, seventh
):
    ann = _user("ann@example.com")
    # six distinct days, two per table: weigh-ins 0-1, workouts 2-3, nutrition logs 4-5
    _weigh_in(ann, day(0), 80)
    _weigh_in(ann, day(1), 80)
    _workout(ann, day(2))
    _workout(ann, day(3))
    _kcal(ann, day(4), 2000)
    _kcal(ann, day(5), 2000)
    # one more row per table on a day another table already has: still six days
    _weigh_in(ann, day(2), 80)
    _workout(ann, day(4))
    _kcal(ann, day(0), 2000)

    days = await _record_days(analytics, ann)
    assert (days, enough_history(days)) == (6, False)  # days 0-5 = 6 < 7

    add = {
        "weigh_in": lambda: _weigh_in(ann, day(6), 80),
        "workout": lambda: _workout(ann, day(6)),
        "nutrition_log": lambda: _kcal(ann, day(6), 2000),
    }
    add[seventh]()  # day 6 is new in every table

    days = await _record_days(analytics, ann)
    assert (days, enough_history(days)) == (7, True)  # days 0-6 = 7 >= 7


# ------------------------------------------------------------------ c) data(): rows


async def test_data_keeps_the_window_edges_and_drops_deleted_and_foreign_rows(analytics):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    start, end = window("month", TODAY)  # day 29 .. today
    assert (start, end) == (day(29), TODAY)

    # weigh-ins on start - 1, start, end, end + 1; one deleted; one of Bob's
    for days_ago, weight in ((30, 81), (29, 80), (0, 79), (-1, 78)):
        _weigh_in(ann, day(days_ago), weight)
    _weigh_in(ann, day(10), 85, deleted=True)
    _weigh_in(bob, day(10), 90)

    # workouts on the same four days (with sets); one deleted with its sets; one of Bob's
    _workout(ann, day(30), [(BENCH, 5, 50, True)])
    first = _workout(ann, day(29), [(BENCH, 5, 100, True), (BENCH, 5, 100, False)])
    last = _workout(ann, TODAY, [(PUSH_UP, 10, 0, True)])
    _workout(ann, day(-1), [(BENCH, 5, 70, True)])
    _workout(ann, day(15), [(BENCH, 3, 120, True)], deleted=True)
    _workout(bob, day(15), [(BENCH, 3, 140, True)])

    # nutrition logs: two on the start day are summed, a deleted one there is not
    _kcal(ann, day(30), 2500)
    _kcal(ann, day(29), 1500)
    _kcal(ann, day(29), 700)
    _kcal(ann, day(29), 999, deleted=True)
    _kcal(ann, TODAY, 1800)
    _kcal(ann, day(-1), 2600)
    _kcal(bob, day(29), 3000)

    data = await _data(analytics, ann, start, end)

    # start 80 and end 79 kept; 81 (start - 1), 78 (end + 1), deleted 85 and Bob's 90 left out
    assert data.weigh_ins == [(day(29), Decimal("80")), (TODAY, Decimal("79"))]
    # start and end kept; day 30, day -1, the deleted day 15 and Bob's day 15 left out
    assert data.workouts == [(first, day(29)), (last, TODAY)]
    # incomplete and 0 kg sets are returned too; the domain decides what counts
    assert sorted(data.sets, key=lambda r: (r.workout_id, r.completed)) == [
        LoggedSetRow(first, day(29), BENCH, "Bench press", 5, Decimal("100"), False),
        LoggedSetRow(first, day(29), BENCH, "Bench press", 5, Decimal("100"), True),
        LoggedSetRow(last, TODAY, PUSH_UP, "Push-up", 10, Decimal("0"), True),
    ]
    assert data.daily_kcal == {
        day(29): Decimal("2200"),  # 1500 + 700; the deleted 999 and Bob's 3000 left out
        TODAY: Decimal("1800"),
    }
    assert (data.training_plan, data.diet_plan) == (None, None)


# ------------------------------------------------------------------ d) plans


async def test_only_the_active_plans_are_returned(analytics):
    ann, bob = _user("ann@example.com"), _user("bob@example.com")
    _training_plan(ann, "archived", 5, day(80))
    _training_plan(ann, "draft", 2)
    _training_plan(ann, "active", 3, day(10))
    _training_plan(bob, "active", 6, day(20))
    _diet_plan(ann, "archived", 2500, day(80))
    _diet_plan(ann, "draft", 1700)
    _diet_plan(ann, "active", 2000, day(5))
    _diet_plan(bob, "active", 3000, day(20))

    data = await _data(analytics, ann, *window("week", TODAY))

    # Ann's active rows: training day 10 .. day 10 + 56, 3 per week (not 5, 2 or Bob's 6)
    assert data.training_plan == ActivePlan(day(10), day(10) + PLAN_DAYS, sessions_per_week=3)
    # diet day 5 .. day 5 + 56, 2000 kcal (not 2500, 1700 or Bob's 3000)
    assert data.diet_plan == ActivePlan(day(5), day(5) + PLAN_DAYS, daily_kcal=2000)


@pytest.mark.parametrize("status", ["draft", "archived"])
async def test_a_draft_or_archived_plan_gives_none(analytics, status):
    ann = _user("ann@example.com")
    start = None if status == "draft" else day(10)
    _training_plan(ann, status, 3, start)
    _diet_plan(ann, status, 2000, start)

    data = await _data(analytics, ann, *window("week", TODAY))

    assert (data.training_plan, data.diet_plan) == (None, None)


# ------------------------------------------------------------------ e) a month end to end


async def test_a_hand_computed_month_through_the_domain_summary(analytics):
    ann = _user("ann@example.com")
    # window: day 29 .. today, 30 days

    # weigh-ins: day 30 is outside; change = 80.5 - 82.0 = -1.5
    _weigh_in(ann, day(30), 90)
    _weigh_in(ann, day(29), 82.0)
    _weigh_in(ann, day(15), 81.2)
    _weigh_in(ann, TODAY, 80.5)

    # training plan from day 13 (mid-window), 3 sessions per week
    _training_plan(ann, "active", 3, day(13))
    # workouts; tonnage counts completed sets with weight > 0
    # W1, day 20, before the plan: 500 + 500 + 480 + 480 = 1960
    _workout(
        ann,
        day(20),
        [(SQUAT, 5, 100, True), (SQUAT, 5, 100, True), (BENCH, 8, 60, True), (BENCH, 8, 60, True)],
    )
    # W2, day 13, the plan start: 525 + 500 + 700 + 2000 = 3725
    _workout(
        ann,
        day(13),
        [
            (SQUAT, 5, 105, True),
            (BENCH, 8, 62.5, True),
            (DEADLIFT, 5, 140, True),
            (DEADLIFT, 20, 100, True),
        ],
    )
    # W3, day 9: 550 + 390 = 940
    _workout(ann, day(9), [(SQUAT, 5, 110, True), (BENCH, 6, 65, True)])
    # W4, day 6: 562.5 + 450 = 1012.5; the incomplete 3 x 120 is not counted
    _workout(
        ann, day(6), [(SQUAT, 5, 112.5, True), (SQUAT, 3, 120, False), (DEADLIFT, 3, 150, True)]
    )
    # W5, day 1: 180 + 0 = 180
    _workout(ann, day(1), [(CURL, 12, 15, True), (PUSH_UP, 15, 0, True)])

    # diet plan from day 4, 2000 kcal: on target = 1800..2200 inclusive
    _diet_plan(ann, "active", 2000, day(4))
    _kcal(ann, day(20), 2500)  # before the plan
    _kcal(ann, day(10), 2100)  # before the plan
    _kcal(ann, day(4), 1800)  # on target (lower edge)
    _kcal(ann, day(3), 2200)  # on target (upper edge)
    _kcal(ann, day(2), 1799)  # off target
    # day 1: no log, fails
    _kcal(ann, TODAY, 1200)  # today 1200 + 800 = 2000, on target
    _kcal(ann, TODAY, 800)

    async with analytics() as store:
        record_days = await store.record_days(ann)
        data = await store.data(ann, *window("month", TODAY))
    s = summary("month", TODAY, record_days, data)

    # distinct days: 30, 29, 15, 0 (weigh-ins) + 20, 13, 9, 6, 1 (workouts)
    # + 10, 4, 3, 2 (kcal; 20 and 0 already counted) = 4 + 5 + 4 = 13
    assert record_days == 13
    assert (s.status, s.period_start, s.period_end) == ("ok", day(29), TODAY)
    assert s.weight_change == Decimal("-1.5")  # last 80.5 - first 82.0 (day 30 is outside)
    assert s.total_workouts == 5  # W1 .. W5
    assert s.avg_workouts_per_week == pytest.approx(7 / 6)  # 5 / (30 / 7) = 35 / 30 = 1.1667
    # days with a log: 20, 10, 4, 3, 2, 0 = 6 (today 1200 + 800 = 2000)
    # (2500 + 2100 + 1800 + 2200 + 1799 + 2000) / 6 = 12399 / 6 = 2066.5
    assert s.avg_calories == 2066.5
    assert s.tonnage == Decimal("7817.5")  # 1960 + 3725 + 940 + 1012.5 + 180
    # covered: day 13 (plan start) .. today = 14 days; planned 3 x 14 / 7 = 6
    # done in the covered part: W2 (13), W3 (9), W4 (6), W5 (1) = 4; W1 (20) is before
    # 4 / 6 x 100 = 66.67
    assert s.workout_compliance_pct == pytest.approx(200 / 3)
    # covered: day 4 (plan start) .. today = 5 days; on target: 4 (1800), 3 (2200), 0 (2000)
    # = 3; off: 2 (1799, |1799 - 2000| = 201 > 200), 1 (no log); 3 / 5 x 100 = 60
    assert s.diet_compliance_pct == pytest.approx(60.0)
    # workouts per exercise: squat W1-W4 = 4, bench W1-W3 = 3, deadlift W2, W4 = 2,
    # curl W5 = 1, push-up W5 = 1 -> squat, bench, deadlift
    # e1RM = w x (30 + reps) / 30 on completed sets with weight > 0 and 1-12 reps
    lifts = [(k.exercise_id, k.exercise_name, k.first_e1rm, k.best_e1rm) for k in s.key_lifts]
    assert lifts == [
        # first (day 20): 100 x 35 / 30 = 116.67
        # best: 112.5 x 35 / 30 = 131.25 (> 110 x 35 / 30 = 128.33, 105 x 35 / 30 = 122.5);
        # the incomplete 120 x 33 / 30 = 132 is not counted
        (SQUAT, "Back squat", pytest.approx(Decimal(350) / 3), Decimal("131.25")),
        # first (day 20): 60 x 38 / 30 = 76
        # best: 62.5 x 38 / 30 = 79.17 (> 65 x 36 / 30 = 78)
        (BENCH, "Bench press", Decimal(76), pytest.approx(Decimal(475) / 6)),
        # first (day 13): 140 x 35 / 30 = 163.33; 100 x 20 reps (= 166.67) has > 12 reps
        # best: 150 x 33 / 30 = 165
        (DEADLIFT, "Deadlift", pytest.approx(Decimal(490) / 3), Decimal(165)),
    ]


# ------------------------------------------------------------------ two ISO weeks


async def test_per_iso_week_inputs_of_the_compliance_series(analytics):
    ann = _user("ann@example.com")
    this_monday = _monday(TODAY)  # today or earlier
    last_monday = this_monday - timedelta(days=7)  # 7-13 days ago: inside the month window

    def last(weekday: int) -> date:  # 0 = last Monday .. 6 = last Sunday
        return last_monday + timedelta(days=weekday)

    _training_plan(ann, "active", 3, last(2))  # from last Wednesday
    _diet_plan(ann, "active", 2000, last(0))  # from last Monday
    for when in (last(0), last(2), last(5), this_monday):  # Mon, Wed, Sat; this Mon
        _workout(ann, when)
    _workout(ann, last(4), deleted=True)  # Fri, deleted
    _kcal(ann, last(0), 1000)  # Mon 1000 + 1000 = 2000, on target
    _kcal(ann, last(0), 1000)
    _kcal(ann, last(1), 2300)  # Tue, off target
    _kcal(ann, last(2), 2000, deleted=True)  # Wed, deleted: no log
    _kcal(ann, last(3), 1900)  # Thu, on target
    _kcal(ann, last(6), 2150)  # Sun, on target
    _kcal(ann, this_monday, 2000)

    data = await _data(analytics, ann, *window("month", TODAY))

    # workouts per Monday-dated week: last week Mon, Wed, Sat = 3 (deleted Fri left out);
    # this week Mon = 1
    assert Counter(_monday(d) for _, d in data.workouts) == {last_monday: 3, this_monday: 1}
    # logged days per week: last week Mon, Tue, Thu, Sun = 4 (deleted Wed left out);
    # this week Mon = 1
    assert Counter(_monday(d) for d in data.daily_kcal) == {last_monday: 4, this_monday: 1}
    # training last Wed .. last Wed + 56, 3 per week; diet last Mon .. last Mon + 56, 2000
    assert data.training_plan == ActivePlan(last(2), last(2) + PLAN_DAYS, sessions_per_week=3)
    assert data.diet_plan == ActivePlan(last(0), last(0) + PLAN_DAYS, daily_kcal=2000)

    # last week through section 7 (the values B-23's per-week series should give)
    week = [last(i) for i in range(7)]  # last Mon .. last Sun, all inside the window
    # training covers last week from its start, last Wed: Wed, Thu, Fri, Sat, Sun = 5 days
    covered = [d for d in week if d >= data.training_plan.start]
    assert len(covered) == 5
    # workouts in Wed .. Sun: Wed and Sat = 2; Mon is before the plan start,
    # the deleted Fri is not returned
    done = sum(1 for _, d in data.workouts if d in covered)
    assert done == 2
    # planned = 3 sessions x 5 days / 7 = 15 / 7 = 2.142857
    # compliance = 2 / (15 / 7) x 100 = 1400 / 15 = 93.33
    assert workout_compliance(done, 3, len(covered)) == pytest.approx(1400 / 15)
    # diet covers the whole week from last Mon = 7 days; on target (1800 .. 2200):
    # Mon 1000 + 1000 = 2000, Thu 1900, Sun 2150 = 3; off: Tue 2300; no log: Wed (deleted),
    # Fri, Sat; 3 / 7 x 100 = 42.86
    assert diet_compliance(week, data.daily_kcal, 2000) == pytest.approx(300 / 7)


# ------------------------------------------------------------------ goal prediction input


async def test_target_weight_is_the_users_own(analytics):
    ann, bob, cid = (_user(f"{n}@example.com") for n in ("ann", "bob", "cid"))
    _profile(ann, 78)
    _profile(bob, 95)
    # cid has no profile

    async with analytics() as store:
        targets = [await store.target_weight(user) for user in (ann, bob, cid)]

    assert targets == [Decimal("78"), Decimal("95"), None]  # each user's own target_value
