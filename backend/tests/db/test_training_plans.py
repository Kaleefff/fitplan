"""Training plans on PostgreSQL with the temporary seed (B-11).

Loads database/dev/temporary_training_seed.sql into the throwaway database; skipped
without PostgreSQL. Delete the seed-coverage test with the seed when DB-02/DB-03 land.
"""

import functools
import itertools
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.training_plans import SqlTrainingPlanStore, SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.domain.constants import DifficultyLevel, Equipment, Goal
from app.domain.training import generate_training_plan
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

SEED = Path(__file__).resolve().parents[3] / "database" / "dev" / "temporary_training_seed.sql"
TODAY = date.today()


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


def _load_seed() -> None:
    connection = _sync_engine().raw_connection()
    try:
        connection.autocommit = True
        connection.cursor().execute(SEED.read_text(encoding="utf-8"))
    finally:
        connection.close()


def _scalar(sql: str, **params):
    with _sync_engine().connect() as db:
        return db.execute(text(sql), params).scalar_one()


@pytest.fixture
def sessions(migrated_db):  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, exercise, exercise_muscle_group, injury_type"
                " RESTART IDENTITY CASCADE"
            )
        )
    _load_seed()
    engine = create_async_engine(database_url().set(database=TEST_DB))
    yield engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def api(sessions) -> Iterator[TestClient]:
    engine, factory = sessions
    repositories = Repositories(
        users=SqlUserRepository(factory),
        refresh_tokens=SqlRefreshTokenRepository(factory),
        profiles=SqlProfileReader(factory),
        workouts=SqlWorkoutUnitOfWork(factory),
        training_plans=SqlTrainingPlanUnitOfWork(factory),
        profile_data=SqlProfileUnitOfWork(factory),
        password_resets=SqlPasswordResetRepository(factory),
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


def _generate(api, headers, goal="strength", days=3, level="beginner", equipment="gym"):
    return api.post(
        "/api/v1/training-plans/generate",
        json={
            "goal": goal,
            "num_training_days": days,
            "experience_level": level,
            "equipment": equipment,
        },
        headers=headers,
    )


# ---------------------------------------------------------------- the temporary seed


def test_seed_is_idempotent_and_covers_every_combination(api, sessions):
    _load_seed()  # a second load changes nothing
    assert _scalar("SELECT count(*) FROM exercise") == 44
    assert _scalar("SELECT count(*) FROM muscle_group") == 10

    _, factory = sessions

    async def load():
        async with factory() as session:
            return await SqlTrainingPlanStore(session).catalogue()

    catalogue = api.portal.call(load)
    for goal, days, level, equipment in itertools.product(
        Goal, range(1, 8), DifficultyLevel, Equipment
    ):
        plan = generate_training_plan(goal, days, level, equipment, [], catalogue)
        assert len(plan.sessions) == days
        assert plan.skipped_groups == ()


# ---------------------------------------------------------------- generate, read, accept


def test_generate_stores_a_draft_with_named_exercises(api):
    headers = _login(api)

    response = _generate(api, headers, goal="muscle_gain", days=4, level="intermediate")

    assert response.status_code == 201
    plan = response.json()
    assert (plan["status"], plan["plan_name"]) == ("draft", "Muscle gain, 4 days per week")
    assert (plan["experience_level"], plan["equipment"]) == ("intermediate", "gym")
    assert (plan["start_date"], plan["end_date"], plan["skipped_muscle_groups"]) == (None, None, [])
    assert [s["session_name"] for s in plan["sessions"]] == [
        "Upper A",
        "Lower A",
        "Upper B",
        "Lower B",
    ]
    first = plan["sessions"][0]["exercises"][0]
    assert first["exercise_name"] and first["planned_weight"] is None
    assert api.get(f"/api/v1/training-plans/{plan['id']}", headers=headers).json() == plan


def test_generating_again_replaces_the_draft(api):
    headers = _login(api)
    first = _generate(api, headers).json()
    second = _generate(api, headers, days=2).json()

    assert second["id"] != first["id"]
    assert _scalar("SELECT count(*) FROM training_plan") == 1
    assert api.get(f"/api/v1/training-plans/{first['id']}", headers=headers).status_code == 404


def test_injured_group_is_skipped(api):
    headers = _login(api)
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "INSERT INTO injury (user_id, injury_type_id, affected_muscle_group_id, severity,"
                " start_date) SELECT 1, t.id, m.id, 'moderate', current_date"
                " FROM injury_type t, muscle_group m"
                " WHERE t.type_name = 'Shoulder strain' AND m.group_name = 'shoulders'"
            )
        )

    plan = _generate(api, headers).json()

    assert plan["skipped_muscle_groups"] == ["shoulders"]
    names = {e["exercise_name"] for s in plan["sessions"] for e in s["exercises"]}
    assert not names & {"Pike push-up", "Dumbbell shoulder press", "Barbell overhead press"}


def test_not_enough_exercises_is_422_with_suggestions_and_keeps_the_draft(api):
    headers = _login(api)
    draft = _generate(api, headers).json()
    with _sync_engine().begin() as db:  # calves only in the gym
        db.execute(
            text(
                "DELETE FROM exercise WHERE name IN"
                " ('Standing calf raise', 'Single-leg dumbbell calf raise')"
            )
        )

    response = _generate(api, headers, goal="muscle_gain", equipment="home")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "insufficient_exercises"
    assert body["details"][:2] == [
        {"field": "muscle_group", "code": "no_eligible_exercise", "muscle_group": "calves"},
        {"code": "change_equipment", "equipment": "gym"},
    ]
    assert body["details"][2]["code"] == "change_goal"
    assert api.get(f"/api/v1/training-plans/{draft['id']}", headers=headers).status_code == 200


def test_accept_activates_and_archives_the_previous_plan(api):
    headers = _login(api)
    assert api.get("/api/v1/training-plans/active", headers=headers).status_code == 404

    first = _generate(api, headers).json()
    accepted = api.post(f"/api/v1/training-plans/{first['id']}/accept", headers=headers)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"
    assert accepted.json()["start_date"] == TODAY.isoformat()
    assert accepted.json()["end_date"] == (TODAY + timedelta(56)).isoformat()
    assert api.get("/api/v1/training-plans/active", headers=headers).json()["id"] == first["id"]

    again = api.post(f"/api/v1/training-plans/{first['id']}/accept", headers=headers)
    assert again.status_code == 409

    second = _generate(api, headers, days=2).json()
    start = (TODAY + timedelta(3)).isoformat()
    api.post(
        f"/api/v1/training-plans/{second['id']}/accept",
        json={"start_date": start},
        headers=headers,
    )
    assert api.get(f"/api/v1/training-plans/{first['id']}", headers=headers).json()["status"] == (
        "archived"
    )
    active = api.get("/api/v1/training-plans/active", headers=headers).json()
    assert (active["id"], active["start_date"]) == (second["id"], start)


def test_another_users_plan_is_404(api):
    ann = _login(api)
    bob = _login(api, "bob@example.com")
    plan = _generate(api, ann).json()

    assert api.get(f"/api/v1/training-plans/{plan['id']}", headers=bob).status_code == 404
    assert api.post(f"/api/v1/training-plans/{plan['id']}/accept", headers=bob).status_code == 404
    assert api.get("/api/v1/training-plans/generate", headers=ann).status_code == 405


# ---------------------------------------------------------------- the whole loop


def test_generate_accept_train_adapt(api):
    """FR-P1 to FR-A5: the baseline workout sets the weights of the generated plan."""
    headers = _login(api)
    plan = _generate(api, headers, goal="strength", days=1, level="intermediate").json()
    api.post(f"/api/v1/training-plans/{plan['id']}/accept", headers=headers)
    session = plan["sessions"][0]
    weighted_id = _scalar(
        "SELECT se.id FROM session_exercise se JOIN exercise e ON e.id = se.exercise_id"
        " WHERE se.training_session_id = :s AND NOT e.is_bodyweight ORDER BY se.sort_order"
        " LIMIT 1",
        s=session["id"],
    )
    weighted = next(e for e in session["exercises"] if e["id"] == weighted_id)
    sets = [
        {"set_number": n, "reps": weighted["planned_reps"], "weight": 40, "completed": True}
        for n in range(1, weighted["planned_sets"] + 1)
    ]

    workout = api.post(
        "/api/v1/workouts",
        json={
            "training_session_id": session["id"],
            "log_date": TODAY.isoformat(),
            "rpe_rating": 8,
            "exercises": [
                {
                    "exercise_id": weighted["exercise_id"],
                    "session_exercise_id": weighted["id"],
                    "sort_order": 1,
                    "sets": sets,
                }
            ],
        },
        headers=headers,
    )

    assert workout.status_code == 201
    adjustment = workout.json()["adjustments"][0]
    assert (adjustment["reason"], adjustment["new_weight"]) == ("baseline", 40.0)
    active = api.get("/api/v1/training-plans/active", headers=headers).json()
    planned = next(
        e for s in active["sessions"] for e in s["exercises"] if e["id"] == weighted["id"]
    )
    assert planned["planned_weight"] == 40.0


def test_next_session_follows_the_schedule_and_skips_a_done_one(api):
    headers = _login(api)
    assert api.get("/api/v1/sessions/next", headers=headers).status_code == 404

    plan = _generate(api, headers, days=7).json()  # a session on every weekday
    api.post(f"/api/v1/training-plans/{plan['id']}/accept", headers=headers)
    today = api.get("/api/v1/sessions/next", headers=headers).json()

    assert (today["training_plan_id"], today["date"]) == (plan["id"], TODAY.isoformat())
    assert today["session"]["day_of_week"] == TODAY.isoweekday()
    first = today["session"]["exercises"][0]
    api.post(
        "/api/v1/workouts",
        json={
            "training_session_id": today["session"]["id"],
            "log_date": TODAY.isoformat(),
            "rpe_rating": 7,
            "exercises": [
                {
                    "exercise_id": first["exercise_id"],
                    "sort_order": 1,
                    "sets": [{"set_number": 1, "reps": 5, "weight": 0, "completed": True}],
                }
            ],
        },
        headers=headers,
    )

    tomorrow = api.get("/api/v1/sessions/next", headers=headers).json()
    assert tomorrow["date"] == (TODAY + timedelta(1)).isoformat()
    assert tomorrow["session"]["day_of_week"] == (TODAY + timedelta(1)).isoweekday()
