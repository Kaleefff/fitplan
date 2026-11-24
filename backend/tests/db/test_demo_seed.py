"""Demo users seed (app/db/demo_seed.py; FR-R1 to FR-R5, test data for M-18 and DB-12).

Uses its own throwaway database (fitplan_demo_seed_test), migrated and loaded with the
reference seed, created and dropped like test_seed.py; skipped when PostgreSQL is not
reachable. TODAY is a fixed Tuesday, except in the API test, whose endpoints use the clock.

The analytics checks run through the real SqlAnalyticsStore and AnalyticsService. The
weekday test (the main guard against a persona drifting off its intended status) feeds
the same service an in-memory store built from the generated rows, for each of the 7
weekdays and for --weeks 52; test_memory_store_matches_the_database shows that store
answers like the SQL one.
"""

import time
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import demo_seed
from app.db.demo_seed import (
    PERSONAS,
    PERSONAS_BY_SLUG,
    DemoRows,
    DemoSeedError,
    SeedResult,
    generate,
    seed,
)
from app.db.repositories.analytics import SqlAnalyticsUnitOfWork
from app.db.seed import load
from app.db.session import database_url
from app.domain.analytics import ActivePlan, AnalyticsData, LoggedSetRow
from app.domain.constants import PLAN_DURATION_DAYS
from app.main import create_app
from app.services.analytics import AnalyticsService
from app.services.repositories import sql_repositories
from tests.clock import today as real_today
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.conftest import delete_users
from tests.db.test_migrations import run_alembic

TEST_DB = "fitplan_demo_seed_test"
TODAY = date(2026, 11, 24)  # a Tuesday
NOW = datetime(2026, 11, 24, 11, 0, tzinfo=UTC)  # 12:00 in Warsaw
ZONE = "Europe/Warsaw"
ROUNDS = 4  # bcrypt cost of the tests; login works with any cost
METRICS = (
    "weight",
    "workouts_per_week",
    "workout_compliance",
    "calories",
    "diet_compliance",
    "tonnage",
)
PERIODS = ("week", "month", "3months")
WITH_HISTORY = ("loss", "gain", "strength", "irregular")
MAIN_LIFTS = {"Barbell back squat", "Barbell bench press", "Barbell deadlift"}
PREDICTION = {
    "loss": ("ok", []),
    "gain": ("ok", []),
    "strength": ("no_target", []),
    "irregular": ("ok", ["low_fit", "gaps", "low_training_compliance"]),
    "newbie": ("insufficient_data", []),
    "fresh": ("insufficient_data", []),
}

# Rows per persona at TODAY with the default history (the counts not listed here are
# checked against the generator and the identities in test_row_counts_per_persona).
# training_plan: plan_periods; the active plan is [TODAY - 55, TODAY + 56 - 55], earlier
#   ones 57 days apart while they start on or after the history start:
#   loss 91 days, gain 56, irregular 70, newbie 9, fresh 2: only the active plan;
#   strength 182 days: active from 30 Sep, archived 4 Aug and 8 Jun (27 May to 7 Jun: none).
# training_session: one per training day per plan (3, 4, 4x3, 3, 3, 3);
# session_exercise: Full body A 4 + B 5 + C 5 (+ D 4) per plan, newbie 4 per session.
# body_metrics: Mon, Wed and Sat of every whole week plus today (a Tuesday):
#   loss 13x3+1 = 40, gain 8x3+1 = 25, strength 26x3+1 = 79; irregular 10x3+1 = 31 minus
#   the 5 Mon/Wed/Sat in days-ago 9 to 20 (4, 7, 9, 11, 14 Nov) = 26; newbie 3, fresh 2.
# workout_log: 7-day blocks back from today, error diffusion from today:
#   loss 0.85x3 per block = 3,2,[3],3,2,[1],3,2,3,2,3,3,2 (overrides in brackets) = 32;
#   gain 0.9x4 = 4,3,4,3,4,4,3,4 = 29; strength 0.8x4 over 26 blocks = 83.2 -> 83;
#   irregular the 10 overrides 1+2+0+2+3+1+0+2+3+1 = 15; newbie block 0 = 3; fresh 0.
EXPECTED = {
    "loss": (1, 3, 14, 1, 40, 32),
    "gain": (1, 4, 18, 1, 25, 29),
    "strength": (3, 12, 54, 3, 79, 83),
    "irregular": (1, 3, 14, 1, 26, 15),
    "newbie": (1, 3, 12, 1, 3, 3),
    "fresh": (1, 3, 14, 1, 2, 0),
}
EXPECTED_TABLES = (
    "training_plan",
    "training_session",
    "session_exercise",
    "diet_plan",
    "body_metrics",
    "workout_log",
)
COUNT_SQL = {
    "app_user": "SELECT count(*) FROM app_user WHERE id = :u",
    "user_profile": "SELECT count(*) FROM user_profile WHERE user_id = :u",
    "training_plan": "SELECT count(*) FROM training_plan WHERE user_id = :u",
    "training_session": "SELECT count(*) FROM training_session s"
    " JOIN training_plan p ON p.id = s.training_plan_id WHERE p.user_id = :u",
    "session_exercise": "SELECT count(*) FROM session_exercise e"
    " JOIN training_session s ON s.id = e.training_session_id"
    " JOIN training_plan p ON p.id = s.training_plan_id WHERE p.user_id = :u",
    "diet_plan": "SELECT count(*) FROM diet_plan WHERE user_id = :u",
    "body_metrics": "SELECT count(*) FROM body_metrics WHERE user_id = :u",
    "workout_log": "SELECT count(*) FROM workout_log WHERE user_id = :u",
    "workout_log_exercise": "SELECT count(*) FROM workout_log_exercise e"
    " JOIN workout_log w ON w.id = e.workout_log_id WHERE w.user_id = :u",
    "workout_set": "SELECT count(*) FROM workout_set s"
    " JOIN workout_log_exercise e ON e.id = s.workout_log_exercise_id"
    " JOIN workout_log w ON w.id = e.workout_log_id WHERE w.user_id = :u",
    "nutrition_log": "SELECT count(*) FROM nutrition_log WHERE user_id = :u",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    admin = create_engine(database_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL is not reachable: run docker compose up -d")

    def recreate(create: bool) -> None:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            if create:
                connection.execute(text(f"CREATE DATABASE {TEST_DB}"))

    recreate(create=True)
    test_engine = create_engine(database_url().set(database=TEST_DB))
    run_alembic(test_engine, "upgrade", "head")
    with test_engine.begin() as connection:
        load(connection)
    yield test_engine
    test_engine.dispose()
    recreate(create=False)
    admin.dispose()


@pytest.fixture
def db(engine: Engine) -> Engine:
    with engine.begin() as connection:
        delete_users(connection)
    return engine


@pytest.fixture
async def service(db: Engine) -> AsyncIterator[AnalyticsService]:
    async_engine = create_async_engine(database_url().set(database=TEST_DB))
    yield AnalyticsService(SqlAnalyticsUnitOfWork(async_sessionmaker(async_engine)))
    await async_engine.dispose()


def run(
    engine: Engine, slugs: list[str] | None = None, weeks: int | None = None, today: date = TODAY
) -> dict[str, SeedResult]:
    personas = [PERSONAS_BY_SLUG[s] for s in slugs] if slugs else PERSONAS
    with engine.begin() as connection:
        results = seed(connection, personas, today, weeks, bcrypt_rounds=ROUNDS)
    return {r.email.removeprefix("demo-").split("@")[0]: r for r in results}


def scalar(engine: Engine, sql: str, **params):
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def rows(engine: Engine, sql: str, **params) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql), params)]


def table_counts(engine: Engine, user_id: int) -> Counter[str]:
    return Counter({table: scalar(engine, sql, u=user_id) for table, sql in COUNT_SQL.items()})


# ---------------------------------------------------------------- rows and dates


def test_every_demo_email_passes_the_api_email_validation():
    for persona in PERSONAS:
        assert TypeAdapter(EmailStr).validate_python(persona.email) == persona.email


def test_row_counts_per_persona(db):
    results = run(db)

    for slug, result in results.items():
        counts = table_counts(db, result.user_id)
        generated = generate(PERSONAS_BY_SLUG[slug], TODAY)
        assert counts == result.counts == generated.counts(), slug
        assert tuple(counts[t] for t in EXPECTED_TABLES) == EXPECTED[slug], slug
        assert counts["app_user"] == counts["user_profile"] == 1
        sets = PERSONAS_BY_SLUG[slug].sets  # 5 for strength, 3 for the others
        assert counts["workout_set"] == sets * counts["workout_log_exercise"], slug
        meals = rows(
            db,
            "SELECT count(*) FROM nutrition_log WHERE user_id = :u GROUP BY log_date",
            u=result.user_id,
        )
        assert all(3 <= n <= 4 for (n,) in meals), slug
    days = "SELECT DISTINCT log_date FROM nutrition_log WHERE user_id = :u"
    assert len(rows(db, days, u=results["newbie"].user_id)) == 6
    assert len(rows(db, days, u=results["fresh"].user_id)) == 2


def test_log_dates_lie_in_the_history(db):
    results = run(db)

    for slug, result in results.items():
        registered, first, last = rows(
            db,
            "SELECT u.registration_date, min(d), max(d) FROM app_user u, ("
            " SELECT measured_on AS d FROM body_metrics WHERE user_id = :u"
            " UNION ALL SELECT log_date FROM workout_log WHERE user_id = :u"
            " UNION ALL SELECT log_date FROM nutrition_log WHERE user_id = :u) days"
            " WHERE u.id = :u GROUP BY u.registration_date",
            u=result.user_id,
        )[0]
        assert registered == generate(PERSONAS_BY_SLUG[slug], TODAY).start, slug
        assert registered <= first and last == TODAY, slug
    assert scalar(db, "SELECT count(*) FROM body_metrics WHERE deleted_at IS NOT NULL") == 0
    assert scalar(db, "SELECT count(*) FROM personal_record") == 0
    assert scalar(db, "SELECT count(*) FROM progress_report") == 0


def test_values_stay_inside_the_constraints_and_photo_logs_are_pairs(db):
    run(db)

    assert scalar(db, "SELECT count(*) FROM workout_log WHERE rpe_rating NOT BETWEEN 6 AND 8") == 0
    assert scalar(db, "SELECT count(*) FROM workout_set WHERE rpe NOT BETWEEN 6 AND 8") == 0
    assert scalar(db, "SELECT count(*) FROM workout_set WHERE NOT completed") > 0
    photo = rows(
        db,
        "SELECT count(*), min(ai_confidence), max(ai_confidence), bool_or(ai_was_edited),"
        " bool_or(NOT ai_was_edited), count(meal_photo_url), count(planned_meal_id)"
        " FROM nutrition_log WHERE ai_confidence IS NOT NULL",
    )[0]
    total = scalar(db, "SELECT count(*) FROM nutrition_log")
    assert 0.1 < photo[0] / total < 0.3  # about 1 in 5
    assert Decimal("0.70") <= photo[1] and photo[2] <= Decimal("0.95")
    assert photo[3] and photo[4] and photo[5] == 0 and photo[6] == 0
    # kcal of each log and of each diet plan match 4/9/4 kcal per g of the macros
    assert scalar(
        db,
        "SELECT max(abs(actual_cals - 4 * actual_protein - 9 * actual_fat - 4 * actual_carbs))"
        " FROM nutrition_log",
    ) <= Decimal("0.05")
    assert scalar(
        db,
        "SELECT max(abs(daily_cal_goal - 4 * protein_goal - 9 * fat_goal - 4 * carbs_goal))"
        " FROM diet_plan",
    ) <= Decimal("0.05")


# ---------------------------------------------------------------- plans


@pytest.mark.parametrize("weeks", [None, 52])
def test_one_active_plan_of_each_kind_covers_today_and_no_two_overlap(db, weeks):
    results = run(db, weeks=weeks)

    for slug, result in results.items():
        for table in ("training_plan", "diet_plan"):
            plans = rows(
                db,
                f"SELECT start_date, end_date, status::text FROM {table}"
                " WHERE user_id = :u ORDER BY start_date",
                u=result.user_id,
            )
            active = [p for p in plans if p[2] == "active"]
            assert len(active) == 1, (slug, table)
            start, end, _ = active[0]
            # as services/training_plans.py and diet_plans.py: end = start + 56 days
            assert end == start + timedelta(PLAN_DURATION_DAYS), (slug, table)
            assert start <= TODAY <= end, (slug, table)
            assert all(e - s == timedelta(PLAN_DURATION_DAYS) for s, e, _ in plans)
            assert all(a[1] < b[0] for a, b in pairwise(plans)), (slug, table)
            assert plans[-1] == active[0]
        dates = "SELECT start_date, end_date FROM {} WHERE user_id = :u ORDER BY 1"
        training = rows(db, dates.format("training_plan"), u=result.user_id)
        assert training == rows(db, dates.format("diet_plan"), u=result.user_id), slug


def test_workouts_link_to_the_plan_in_force_and_none_before_the_first_plan(db):
    results = run(db)

    for slug in ("loss", "strength", "irregular"):  # the ones with days before the first plan
        user = results[slug].user_id
        first_plan = scalar(
            db, "SELECT min(start_date) FROM training_plan WHERE user_id = :u", u=user
        )
        before = rows(
            db,
            "SELECT training_session_id FROM workout_log WHERE user_id = :u AND log_date < :d",
            u=user,
            d=first_plan,
        )
        assert before and all(session is None for (session,) in before), slug
        assert (
            scalar(
                db,
                "SELECT count(*) FROM workout_log_exercise e JOIN workout_log w"
                " ON w.id = e.workout_log_id WHERE w.user_id = :u AND w.log_date < :d"
                " AND e.session_exercise_id IS NOT NULL",
                u=user,
                d=first_plan,
            )
            == 0
        )
    for slug, result in results.items():
        # every other workout: the session of the plan whose dates contain it, on its weekday
        wrong = scalar(
            db,
            "SELECT count(*) FROM workout_log w"
            " JOIN training_plan p ON p.user_id = w.user_id"
            "  AND w.log_date BETWEEN p.start_date AND p.end_date"
            " LEFT JOIN training_session s ON s.id = w.training_session_id"
            " WHERE w.user_id = :u AND (s.training_plan_id IS DISTINCT FROM p.id"
            "  OR s.day_of_week <> extract(isodow FROM w.log_date))",
            u=result.user_id,
        )
        assert wrong == 0, slug
        unlinked = scalar(
            db,
            "SELECT count(*) FROM workout_log_exercise e JOIN workout_log w"
            " ON w.id = e.workout_log_id JOIN session_exercise se ON se.id = e.session_exercise_id"
            " WHERE w.user_id = :u AND (se.training_session_id <> w.training_session_id"
            "  OR se.exercise_id <> e.exercise_id OR se.sort_order <> e.sort_order)",
            u=result.user_id,
        )
        assert unlinked == 0, slug


# ---------------------------------------------------------------- replacement


def _other_user(engine: Engine) -> int:
    with engine.begin() as connection:
        user = connection.execute(
            text(
                "INSERT INTO app_user (email, password_hash, name, surname)"
                " VALUES ('ann@example.com', '$2b$04$hash', 'Ann', 'Nowak') RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text("INSERT INTO body_metrics (user_id, measured_on, weight) VALUES (:u, :d, 70)"),
            {"u": user, "d": TODAY},
        )
        log = connection.execute(
            text(
                "INSERT INTO workout_log (user_id, log_date, rpe_rating) VALUES (:u, :d, 7)"
                " RETURNING id"
            ),
            {"u": user, "d": TODAY},
        ).scalar_one()
        logged = connection.execute(
            text(
                "INSERT INTO workout_log_exercise (workout_log_id, exercise_id, sort_order)"
                " SELECT :l, id, 1 FROM exercise WHERE name = 'Barbell bench press'"
                " AND user_id IS NULL RETURNING id"
            ),
            {"l": log},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO workout_set (workout_log_exercise_id, set_number, reps, weight)"
                " VALUES (:x, 1, 5, 60)"
            ),
            {"x": logged},
        )
    return user


def _snapshot(engine: Engine, user: int) -> list[list[tuple]]:
    return [
        rows(engine, "SELECT * FROM app_user WHERE id = :u", u=user),
        rows(engine, "SELECT * FROM body_metrics WHERE user_id = :u ORDER BY id", u=user),
        rows(engine, "SELECT * FROM workout_log WHERE user_id = :u ORDER BY id", u=user),
        rows(
            engine,
            "SELECT s.* FROM workout_set s JOIN workout_log_exercise e"
            " ON e.id = s.workout_log_exercise_id JOIN workout_log w ON w.id = e.workout_log_id"
            " WHERE w.user_id = :u ORDER BY s.id",
            u=user,
        ),
    ]


def test_a_second_run_replaces_the_demo_accounts_and_leaves_other_users(db):
    other = _other_user(db)
    before = _snapshot(db, other)

    first = run(db)
    second = run(db)

    assert _snapshot(db, other) == before
    for slug in first:
        assert first[slug].counts == second[slug].counts
        assert second[slug].user_id != first[slug].user_id
        assert table_counts(db, second[slug].user_id) == second[slug].counts
        assert scalar(db, "SELECT count(*) FROM app_user WHERE id = :u", u=first[slug].user_id) == 0
    assert scalar(db, "SELECT count(*) FROM app_user") == len(PERSONAS) + 1


def test_only_replaces_just_that_account(db):
    other = _other_user(db)
    first = run(db)
    before = {slug: table_counts(db, r.user_id) for slug, r in first.items()}

    again = run(db, ["loss"])

    assert list(again) == ["loss"] and again["loss"].user_id != first["loss"].user_id
    for slug, result in first.items():
        if slug != "loss":
            assert table_counts(db, result.user_id) == before[slug], slug
    assert scalar(db, "SELECT count(*) FROM app_user WHERE id = :u", u=other) == 1


def test_the_email_is_matched_whatever_the_case(db):
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app_user (email, password_hash, name, surname)"
                " VALUES ('DEMO-Loss@Example.COM', 'x', 'Old', 'Account')"
            )
        )

    run(db, ["loss"])

    assert rows(db, "SELECT email, name FROM app_user WHERE lower(email) LIKE 'demo-loss@%'") == [
        ("demo-loss@example.com", "Demo")
    ]


def test_a_missing_library_exercise_changes_nothing(db):
    first = run(db)
    ids = sorted(r.user_id for r in first.values())

    with db.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text(
                "UPDATE exercise SET name = 'Goblet squat (renamed)'"
                " WHERE name = 'Goblet squat' AND user_id IS NULL"
            )
        )
        with pytest.raises(DemoSeedError, match="Goblet squat"):
            seed(connection, PERSONAS, TODAY, bcrypt_rounds=ROUNDS)
        kept = sorted(connection.execute(text("SELECT id FROM app_user")).scalars())
        transaction.rollback()

    assert kept == ids


def test_the_command_line_reports_each_account(db, monkeypatch, capsys):
    monkeypatch.setattr(demo_seed, "create_sync_engine", lambda: create_engine(db.url))
    monkeypatch.setattr(demo_seed, "get_settings", lambda: make_settings())

    assert demo_seed.main(["--only", "loss", "fresh", "--today", TODAY.isoformat()]) == 0

    out = capsys.readouterr().out
    assert "password for every account: demo12345" in out
    assert "demo-loss@example.com" in out and "demo-fresh@example.com" in out
    assert "demo-gain@example.com" not in out
    assert scalar(db, "SELECT count(*) FROM app_user") == 2


def test_a_year_of_history_is_fast_enough(db):
    started = time.perf_counter()
    results = run(db, weeks=52)
    elapsed = time.perf_counter() - started
    total = sum(sum(r.counts.values()) for r in results.values())
    print(f"\n--weeks 52: {elapsed:.1f} s, {total} rows")

    for slug in WITH_HISTORY:
        user = results[slug].user_id
        assert scalar(db, "SELECT registration_date FROM app_user WHERE id = :u", u=user) == (
            TODAY - timedelta(days=52 * 7 - 1)
        )
        assert scalar(db, "SELECT count(*) FROM training_plan WHERE user_id = :u", u=user) == 6
    # newbie and fresh keep their short history
    assert results["newbie"].counts == generate(PERSONAS_BY_SLUG["newbie"], TODAY).counts()
    assert elapsed < 60


# ---------------------------------------------------------------- analytics


async def _check_persona(
    service: AnalyticsService, user_id: int, slug: str, now: datetime
) -> dict[tuple[str, str], list]:
    """Every status of the Stats screen for one persona; returns the chart points."""
    points = {}
    for period in PERIODS:
        summary = await service.summary(user_id, period, ZONE, now)
        assert summary.status == ("insufficient_data" if slug == "fresh" else "ok"), (slug, period)
        if slug in WITH_HISTORY and period == "3months":
            assert {lift.exercise_name for lift in summary.key_lifts} == MAIN_LIFTS, slug
        for metric in METRICS:
            status, series = await service.chart(user_id, metric, period, ZONE, now)
            points[metric, period] = series
            if slug == "fresh":
                assert (status, series) == ("insufficient_data", []), (slug, metric, period)
                continue
            assert status == "ok", (slug, metric, period)
            if slug in WITH_HISTORY:
                assert any(v is not None for _, v in series), (slug, metric, period)
    prediction = await service.goal_prediction(user_id, ZONE, now)
    status, warnings = PREDICTION[slug]
    assert (prediction.status, prediction.warnings) == (status, warnings), slug
    if status == "ok":
        assert prediction.estimated_date is not None
        assert (
            prediction.slope_kg_per_day > 0 if slug == "gain" else prediction.slope_kg_per_day < 0
        )
    return points


@pytest.mark.anyio
@pytest.mark.parametrize("slug", [p.slug for p in PERSONAS])
async def test_the_stats_screen_of_each_persona(db, service, slug):
    user = run(db, [slug])[slug].user_id

    points = await _check_persona(service, user, slug, NOW)

    if slug in ("loss", "strength", "irregular"):
        # compliance weeks wholly before the active plan are null, the others are not
        active = scalar(
            db,
            "SELECT start_date FROM training_plan WHERE user_id = :u AND status = 'active'",
            u=user,
        )
        for metric in ("workout_compliance", "diet_compliance"):
            series = points[metric, "3months"]
            before = [v for monday, v in series if monday + timedelta(days=6) < active]
            after = [v for monday, v in series if monday >= active]
            assert before and all(v is None for v in before), (slug, metric)
            assert after and all(v is not None for v in after), (slug, metric)
    if slug == "strength":  # 3 months fully filled
        weights = points["weight", "3months"]
        assert weights[0][0] <= TODAY - timedelta(days=89 - 6)
        assert all(v > 0 for _, v in points["workouts_per_week", "3months"][1:])


@pytest.mark.anyio
async def test_irregular_complies_less_than_loss_and_strength_has_the_most_tonnage(db, service):
    users = {slug: r.user_id for slug, r in run(db).items()}

    summaries = {
        slug: await service.summary(users[slug], "3months", ZONE, NOW) for slug in WITH_HISTORY
    }

    loss, irregular = summaries["loss"], summaries["irregular"]
    assert irregular.workout_compliance_pct < loss.workout_compliance_pct
    assert irregular.diet_compliance_pct < loss.diet_compliance_pct
    assert summaries["strength"].tonnage == max(s.tonnage for s in summaries.values())


# ---------------------------------------------------------------- weekday guard


class MemoryStore:
    """AnalyticsStore over generated rows, with the semantics of SqlAnalyticsStore."""

    def __init__(self, generated: DemoRows, exercise_ids: dict[str, int] | None = None) -> None:
        self._rows = generated
        names = sorted(generated.exercise_names())
        self._ids = exercise_ids or {name: i for i, name in enumerate(names, start=1)}

    async def record_days(self, user_id: int) -> int:
        r = self._rows
        return len(
            {w["measured_on"] for w in r.weigh_ins}
            | {w.log["log_date"] for w in r.workouts}
            | {n["log_date"] for n in r.nutrition_logs}
        )

    async def data(self, user_id: int, start: date, end: date) -> AnalyticsData:
        r = self._rows
        workouts = [
            (i, w.log["log_date"])
            for i, w in enumerate(r.workouts, start=1)
            if start <= w.log["log_date"] <= end
        ]
        kept = {i for i, _ in workouts}
        daily: dict[date, Decimal] = {}
        for n in r.nutrition_logs:
            if start <= n["log_date"] <= end:
                daily[n["log_date"]] = daily.get(n["log_date"], Decimal(0)) + n["actual_cals"]
        training = next(p.plan for p in r.training_plans if p.plan["status"] == "active")
        diet = next(p for p in r.diet_plans if p["status"] == "active")
        return AnalyticsData(
            weigh_ins=[
                (w["measured_on"], w["weight"])
                for w in r.weigh_ins
                if start <= w["measured_on"] <= end
            ],
            workouts=workouts,
            sets=[
                LoggedSetRow(
                    i,
                    w.log["log_date"],
                    self._ids[e.exercise],
                    e.exercise,
                    s["reps"],
                    s["weight"],
                    s["completed"],
                )
                for i, w in enumerate(r.workouts, start=1)
                if i in kept
                for e in w.exercises
                for s in e.sets
            ],
            daily_kcal=daily,
            training_plan=ActivePlan(
                training["start_date"],
                training["end_date"],
                sessions_per_week=training["num_training_days"],
            ),
            diet_plan=ActivePlan(
                diet["start_date"], diet["end_date"], daily_kcal=diet["daily_cal_goal"]
            ),
        )

    async def target_weight(self, user_id: int) -> Decimal | None:
        return self._rows.profile["target_value"]


def memory_service(
    generated: DemoRows, exercise_ids: dict[str, int] | None = None
) -> AnalyticsService:
    store = MemoryStore(generated, exercise_ids)

    @asynccontextmanager
    async def unit_of_work():
        yield store

    return AnalyticsService(unit_of_work)


@pytest.mark.anyio
@pytest.mark.parametrize("weeks", [None, 52])
@pytest.mark.parametrize("offset", range(7))
async def test_every_persona_keeps_its_statuses_on_every_weekday(offset, weeks):
    today = TODAY + timedelta(days=offset)
    now = datetime.combine(today, NOW.timetz())
    for persona in PERSONAS:
        generated = generate(persona, today, weeks)
        await _check_persona(memory_service(generated), 0, persona.slug, now)
        if persona.slug == "loss":
            loss = await memory_service(generated).summary(0, "3months", ZONE, now)
        if persona.slug == "irregular":
            irregular = await memory_service(generated).summary(0, "3months", ZONE, now)
    assert irregular.workout_compliance_pct < loss.workout_compliance_pct
    assert irregular.diet_compliance_pct < loss.diet_compliance_pct


@pytest.mark.anyio
async def test_memory_store_matches_the_database(db, service):
    users = {slug: r.user_id for slug, r in run(db).items()}
    with db.connect() as connection:
        ids = dict(
            connection.execute(text("SELECT name, id FROM exercise WHERE user_id IS NULL")).all()
        )

    for persona in PERSONAS:
        memory = memory_service(generate(persona, TODAY), ids)
        user = users[persona.slug]
        for period in PERIODS:
            assert await memory.summary(0, period, ZONE, NOW) == await service.summary(
                user, period, ZONE, NOW
            ), (persona.slug, period)
            for metric in METRICS:
                assert await memory.chart(0, metric, period, ZONE, NOW) == await service.chart(
                    user, metric, period, ZONE, NOW
                ), (persona.slug, metric, period)
        assert await memory.goal_prediction(0, ZONE, NOW) == await service.goal_prediction(
            user, ZONE, NOW
        ), persona.slug


# ---------------------------------------------------------------- the real API


@pytest.fixture
def api(db: Engine) -> Iterator[TestClient]:
    async_engine = create_async_engine(database_url().set(database=TEST_DB))
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    app = create_app(
        settings=make_settings(),
        health_checker=FakeHealthChecker(),
        repositories=sql_repositories(sessions),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(async_engine.dispose)


def test_demo_loss_logs_in_and_reads_charts_and_logs_without_items(db, api):
    today = real_today()  # the endpoints use the clock
    run(db, ["loss"], today=today)
    login = api.post(
        "/api/v1/auth/login", json={"email": "demo-loss@example.com", "password": "demo12345"}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    chart = api.get(
        "/api/v1/analytics/charts/weight", params={"period": "3months"}, headers=headers
    )
    assert chart.status_code == 200, chart.text
    assert chart.json()["status"] == "ok" and len(chart.json()["points"]) > 20

    logged_day = max(
        n["log_date"] for n in generate(PERSONAS_BY_SLUG["loss"], today).nutrition_logs
    ).isoformat()
    page = api.get(
        "/api/v1/nutrition-logs", params={"from": logged_day, "to": logged_day}, headers=headers
    )
    summary = api.get(
        "/api/v1/nutrition/daily-summary", params={"date": logged_day}, headers=headers
    )
    print(f"\nGET /nutrition-logs?from={logged_day}&to={logged_day} -> {page.status_code}")
    print(page.text)
    print(f"GET /nutrition/daily-summary?date={logged_day} -> {summary.status_code}")
    print(summary.text)

    assert page.status_code == 200 and summary.status_code == 200
    assert page.json()["total"] == len(page.json()["items"]) >= 3
    assert all(log["items"] == [] for log in page.json()["items"])
    assert [log["id"] for log in summary.json()["logs"]] == sorted(
        log["id"] for log in page.json()["items"]
    )
    assert all(log["items"] == [] for log in summary.json()["logs"])
    assert summary.json()["targets"]["kcal"] == 2250.0
