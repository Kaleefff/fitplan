"""Analytics on PostgreSQL (B-23): the queries feed the domain math end to end.

The rows below are the hand-computed fixture of tests/domain/test_analytics.py, stored
relative to today; skipped without PostgreSQL.
"""

import functools
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.analytics import SqlAnalyticsUnitOfWork
from app.db.repositories.body_metrics import SqlBodyMetricsUnitOfWork
from app.db.repositories.diet_plans import SqlDietPlanUnitOfWork
from app.db.repositories.library import SqlLibraryRepository
from app.db.repositories.nutrition_logs import SqlNutritionLogUnitOfWork
from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.schedule import SqlScheduleUnitOfWork
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.domain.prediction import predict_goal
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

TODAY = date.today()


def day(n: int) -> date:
    return TODAY - timedelta(days=n)


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
def api(migrated_db) -> Iterator[TestClient]:  # noqa: F811
    _sql("TRUNCATE app_user, exercise, muscle_group RESTART IDENTITY CASCADE")
    _sql(
        "INSERT INTO exercise (id, name, difficulty_level, equipment, is_compound, description,"
        " instruction) VALUES (10, 'Bench press', 'beginner', 'gym', true, '', ''),"
        " (11, 'Push-up', 'beginner', 'none', true, '', '')"
    )
    engine = create_async_engine(database_url().set(database=TEST_DB))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repositories = Repositories(
        users=SqlUserRepository(factory),
        refresh_tokens=SqlRefreshTokenRepository(factory),
        profiles=SqlProfileReader(factory),
        workouts=SqlWorkoutUnitOfWork(factory),
        training_plans=SqlTrainingPlanUnitOfWork(factory),
        profile_data=SqlProfileUnitOfWork(factory),
        password_resets=SqlPasswordResetRepository(factory),
        body_metrics=SqlBodyMetricsUnitOfWork(factory),
        schedule=SqlScheduleUnitOfWork(factory),
        diet_plans=SqlDietPlanUnitOfWork(factory),
        analytics=SqlAnalyticsUnitOfWork(factory),
        library=SqlLibraryRepository(factory),
        nutrition_logs=SqlNutritionLogUnitOfWork(factory),
    )
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), repositories=repositories
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(engine.dispose)


def _login(api, email="ann@example.com") -> dict[str, str]:
    pair = api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "name": "A", "surname": "B"},
    ).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}


def _weigh_in(user: int, days_ago: int, weight) -> None:
    _sql(
        "INSERT INTO body_metrics (user_id, measured_on, weight) VALUES (:u, :d, :w)",
        u=user,
        d=day(days_ago),
        w=weight,
    )


def _workout(user: int, days_ago: int, sets: list[tuple[int, int, float, bool]]) -> None:
    log = _sql(
        "INSERT INTO workout_log (user_id, log_date, rpe_rating) VALUES (:u, :d, 7) RETURNING id",
        u=user,
        d=day(days_ago),
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


def _kcal(user: int, days_ago: int, kcal: int) -> None:
    _sql(
        "INSERT INTO nutrition_log (user_id, log_date, meal_type, actual_cals, actual_protein,"
        " actual_fat, actual_carbs) VALUES (:u, :d, 'lunch', :k, 0, 0, 0)",
        u=user,
        d=day(days_ago),
        k=kcal,
    )


def _fixture_week(user: int) -> None:
    _weigh_in(user, 6, 80.0)
    _weigh_in(user, 2, 79.4)
    _workout(user, 5, [(10, 10, 60, True), (10, 8, 60, True), (11, 12, 0, True)])
    _workout(user, 1, [(10, 5, 70, True), (10, 5, 70, False)])
    for days_ago, kcal in ((4, 2000), (3, 2300), (0, 1700)):
        _kcal(user, days_ago, kcal)
    _sql(
        "INSERT INTO training_plan (user_id, plan_name, goal, num_training_days,"
        " experience_level, equipment, status, start_date, end_date)"
        " VALUES (:u, 'P', 'strength', 3, 'beginner', 'gym', 'active', :s, :s + 56)",
        u=user,
        s=day(5),
    )
    _sql(
        "INSERT INTO diet_plan (user_id, name, goal, meals_per_day, daily_cal_goal, protein_goal,"
        " fat_goal, carbs_goal, status, start_date, end_date)"
        " VALUES (:u, 'D', 'maintenance', 3, 2000, 100, 60, 250, 'active', :s, :s + 56)",
        u=user,
        s=day(4),
    )


def test_summary_equals_the_hand_computed_fixture(api):
    headers = _login(api)
    _fixture_week(1)

    s = api.get("/api/v1/analytics/summary", params={"period": "week"}, headers=headers).json()

    assert s == {
        "status": "ok",
        "period": "week",
        "period_start": day(6).isoformat(),
        "period_end": TODAY.isoformat(),
        "weight_change": -0.6,
        "total_workouts": 2,
        "avg_workouts_per_week": 2.0,
        "avg_calories": 2000.0,
        "tonnage": 1430.0,
        "workout_compliance_pct": 77.8,  # 2 / (3 x 6 / 7) x 100
        "diet_compliance_pct": 20.0,  # 1 of 5 days within 1800-2200
        "key_lifts": [
            {
                "exercise_id": 10,
                "exercise_name": "Bench press",
                "first_e1rm": 80.0,  # 60 x 10
                "best_e1rm": 81.67,  # 70 x 5
            }
        ],
    }


def test_charts(api):
    headers = _login(api)
    _fixture_week(1)

    def points(metric):
        body = api.get(f"/api/v1/analytics/charts/{metric}", headers=headers).json()
        assert (body["status"], body["metric"], body["period"]) == ("ok", metric, "week")
        return [(p["date"], p["value"]) for p in body["points"]]

    assert points("weight") == [(day(6).isoformat(), 80.0), (day(2).isoformat(), 79.4)]
    assert points("tonnage") == [(day(5).isoformat(), 1080.0), (day(1).isoformat(), 350.0)]
    assert points("calories") == [
        (day(4).isoformat(), 2000.0),
        (day(3).isoformat(), 2300.0),
        (TODAY.isoformat(), 1700.0),
    ]
    weeks = points("workouts_per_week")
    assert sum(value for _, value in weeks) == 2.0
    assert all(date.fromisoformat(d).weekday() == 0 for d, _ in weeks)  # dated Monday


def test_six_days_of_history_is_insufficient_and_other_users_see_nothing(api):
    headers = _login(api)
    for days_ago in range(6):
        _weigh_in(1, days_ago, 80)

    s = api.get("/api/v1/analytics/summary", headers=headers).json()
    chart = api.get("/api/v1/analytics/charts/weight", headers=headers).json()

    assert (s["status"], s["total_workouts"], s["key_lifts"]) == ("insufficient_data", None, [])
    assert (chart["status"], chart["points"]) == ("insufficient_data", [])
    _weigh_in(1, 6, 80)
    assert api.get("/api/v1/analytics/summary", headers=headers).json()["status"] == "ok"
    bob = _login(api, "bob@example.com")
    assert api.get("/api/v1/analytics/summary", headers=bob).json()["status"] == "insufficient_data"


def test_goal_prediction_matches_the_domain_on_the_stored_weigh_ins(api):
    headers = _login(api)
    api.put(
        "/api/v1/users/me/profile",
        json={
            "age": 30,
            "sex": "male",
            "current_weight": 90,
            "height": 180,
            "activity_level_pal": 1.55,
            "goal": "weight_loss",
            "experience_level": "beginner",
            "equipment": "gym",
            "target_value": 78,
        },
        headers=headers,
    )
    weigh_ins = [
        (day(n), Decimal(str(round(90 - 0.5 / 7 * (27 - n), 2)))) for n in range(27, -1, -3)
    ]
    for when, weight in weigh_ins:
        _weigh_in(1, (TODAY - when).days, weight)
    _weigh_in(1, 40, 95)  # outside the 28-day window

    response = api.get("/api/v1/analytics/goal-prediction", headers=headers).json()

    expected = predict_goal(weigh_ins, Decimal("78"), TODAY, None)
    assert response["status"] == expected.status.value == "ok"
    assert response["estimated_date"] == expected.estimated_date.isoformat()
    assert response["slope_kg_per_week"] == pytest.approx(-0.5, abs=0.01)
    assert response["r_squared"] == pytest.approx(1.0, abs=0.01)
    assert (response["warnings"], response["irregular_data"]) == ([], False)


def test_goal_prediction_without_a_target(api):
    headers = _login(api)
    body = api.get("/api/v1/analytics/goal-prediction", headers=headers).json()
    assert body == {
        "status": "no_target",
        "estimated_date": None,
        "slope_kg_per_week": None,
        "r_squared": None,
        "warnings": [],
        "irregular_data": False,
    }
