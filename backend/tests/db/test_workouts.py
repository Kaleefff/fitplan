"""Workouts on PostgreSQL (B-15, B-16): logging, adaptation, records, idempotency.

The vectors of algorithms.md section 6 run through POST /workouts against a real plan;
skipped without PostgreSQL.
"""

import asyncio
import functools
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from app.services.workouts import ExerciseIn, SetIn, WorkoutIn, WorkoutService
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

TODAY = date.today()
BENCH, SQUAT, PUSH_UP, ROW = 1, 2, 3, 4  # exercise ids of the seed below


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


SEED = """
INSERT INTO muscle_group (id, group_name, region, description) VALUES
  (1, 'chest', 'upper', ''), (2, 'quadriceps', 'lower', ''), (3, 'back', 'upper', '');
INSERT INTO exercise (id, name, difficulty_level, equipment, is_compound, is_bodyweight,
                      description, instruction) VALUES
  (1, 'Bench press', 'beginner', 'gym', true, false, '', ''),
  (2, 'Back squat', 'beginner', 'gym', true, false, '', ''),
  (3, 'Push-up', 'beginner', 'none', true, true, '', ''),
  (4, 'Barbell row', 'beginner', 'gym', true, false, '', '');
INSERT INTO exercise_muscle_group (exercise_id, muscle_group_id, is_primary) VALUES
  (1, 1, true), (2, 2, true), (3, 1, true), (4, 3, true);
"""


def _plan(user_id: int, status: str = "active") -> dict[int, int]:
    """One session, 3 x 10 each: bench 60, squat 100, push-up bodyweight, row without
    a planned weight. Returns exercise id -> session_exercise id; session id is in [0]."""
    with _sync_engine().begin() as db:
        plan_id = db.execute(
            text(
                "INSERT INTO training_plan (user_id, plan_name, goal, num_training_days,"
                " experience_level, equipment, status, start_date, end_date)"
                " VALUES (:u, 'Plan', 'strength', 1, 'beginner', 'gym', :s, :d, :d + 56)"
                " RETURNING id"
            ),
            {"u": user_id, "s": status, "d": TODAY},
        ).scalar_one()
        session_id = db.execute(
            text(
                "INSERT INTO training_session (training_plan_id, session_order, session_name,"
                " day_of_week, estimated_duration) VALUES (:p, 1, 'Full Body', 3, 60)"
                " RETURNING id"
            ),
            {"p": plan_id},
        ).scalar_one()
        ids = {0: session_id}
        for order, (exercise_id, weight) in enumerate(
            [(BENCH, 60), (SQUAT, 100), (PUSH_UP, None), (ROW, None)], start=1
        ):
            ids[exercise_id] = db.execute(
                text(
                    "INSERT INTO session_exercise (training_session_id, exercise_id, sort_order,"
                    " planned_sets, planned_reps, planned_weight, rest_seconds)"
                    " VALUES (:s, :e, :o, 3, 10, :w, 120) RETURNING id"
                ),
                {"s": session_id, "e": exercise_id, "o": order, "w": weight},
            ).scalar_one()
    return ids


def _planned(session_exercise_id: int) -> tuple:
    with _sync_engine().connect() as db:
        row = db.execute(
            text(
                "SELECT planned_sets, planned_reps, planned_weight FROM session_exercise"
                " WHERE id = :id"
            ),
            {"id": session_exercise_id},
        ).one()
    return row[0], row[1], None if row[2] is None else float(row[2])


def _count(table: str) -> int:
    with _sync_engine().connect() as db:
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@pytest.fixture
def sessions(migrated_db):  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, exercise, exercise_muscle_group"
                " RESTART IDENTITY CASCADE"
            )
        )
        db.execute(text(SEED))
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


def _sets(weights, reps=10, completed=None, rpe=None):
    completed = completed or [True] * len(weights)
    return [
        {"set_number": n, "reps": reps, "weight": w, "completed": c, "rpe": rpe}
        for n, (w, c) in enumerate(zip(weights, completed, strict=True), start=1)
    ]


def _workout(plan, exercise_id, sets, rpe, **extra):
    return {
        "training_session_id": plan[0],
        "log_date": TODAY.isoformat(),
        "rpe_rating": rpe,
        "exercises": [
            {
                "exercise_id": exercise_id,
                "session_exercise_id": plan[exercise_id],
                "sort_order": 1,
                "sets": sets,
            }
        ],
        **extra,
    }


def _post(api, headers, body):
    return api.post("/api/v1/workouts", json=body, headers=headers)


# ---------------------------------------------------------------- algorithms.md 6 vectors


@pytest.mark.parametrize(
    ("case", "exercise", "sets", "rpe", "expected"),
    [
        ("A", BENCH, _sets([60, 60, 60]), 6, ("progression", 3, 10, 62.5)),
        ("B", SQUAT, _sets([100, 100, 100]), 7, ("progression", 3, 10, 105.0)),
        ("C", BENCH, _sets([60, 60, 60]), 9, ("reduce_high_rpe", 3, 10, 55.0)),
        (
            "D",
            BENCH,
            _sets([60, 60, 60], completed=[True, True, False]),
            8,
            ("reduce_incomplete_set", 3, 10, 55.0),
        ),
        ("E", BENCH, _sets([60, 60, 60]), 8, None),
        ("G", ROW, _sets([40, 42.5, 42.5]), 8, ("baseline", 3, 10, 42.5)),
        ("H", PUSH_UP, _sets([0, 0, 0]), 6, ("progression", 3, 11, None)),
        ("I", PUSH_UP, _sets([0, 0, 0]), 9, ("reduce_high_rpe", 2, 10, None)),
        ("K", BENCH, _sets([55, 55, 55]), 6, None),
    ],
)
def test_vector(api, case, exercise, sets, rpe, expected):
    headers = _login(api)
    plan = _plan(1)
    before = _planned(plan[exercise])

    response = _post(api, headers, _workout(plan, exercise, sets, rpe))

    assert response.status_code == 201
    adjustments = response.json()["adjustments"]
    if expected is None:
        assert adjustments == []
        assert _planned(plan[exercise]) == before
        assert _count("plan_adjustment") == 0
        return
    reason, new_sets, new_reps, new_weight = expected
    assert adjustments == [
        {
            "session_exercise_id": plan[exercise],
            "reason": reason,
            "old_sets": before[0],
            "new_sets": new_sets,
            "old_reps": before[1],
            "new_reps": new_reps,
            "old_weight": before[2],
            "new_weight": new_weight,
        }
    ]
    assert _planned(plan[exercise]) == (new_sets, new_reps, new_weight)


def test_archived_plan_is_logged_but_not_adapted(api):
    headers = _login(api)
    plan = _plan(1, status="archived")

    response = _post(api, headers, _workout(plan, BENCH, _sets([60, 60, 60]), 6))

    assert response.status_code == 201
    assert response.json()["adjustments"] == []
    assert _planned(plan[BENCH]) == (3, 10, 60.0)


def test_workout_without_a_session_is_logged_and_matched_by_nothing(api):
    headers = _login(api)
    body = {
        "log_date": TODAY.isoformat(),
        "rpe_rating": 7,
        "exercises": [{"exercise_id": BENCH, "sort_order": 1, "sets": _sets([50])}],
    }
    response = _post(api, headers, body)

    assert response.status_code == 201
    workout = response.json()["workout"]
    assert workout["training_session_id"] is None
    assert workout["exercises"][0]["exercise_name"] == "Bench press"
    assert workout["exercises"][0]["session_exercise_id"] is None


def test_exercise_is_matched_to_the_plan_by_exercise_id(api):
    headers = _login(api)
    plan = _plan(1)
    body = _workout(plan, BENCH, _sets([60, 60, 60]), 6)
    del body["exercises"][0]["session_exercise_id"]

    result = _post(api, headers, body).json()

    assert result["workout"]["exercises"][0]["session_exercise_id"] == plan[BENCH]
    assert result["adjustments"][0]["reason"] == "progression"


# ---------------------------------------------------------------- personal records


def test_personal_records_and_achievement_notifications(api):
    headers = _login(api)
    plan = _plan(1)

    first = _post(api, headers, _workout(plan, BENCH, _sets([60, 60, 60]), 8)).json()
    assert [
        (r["exercise_id"], r["max_weight"], r["max_reps"]) for r in first["new_personal_records"]
    ] == [(BENCH, 60.0, 10)]

    same = _post(api, headers, _workout(plan, BENCH, _sets([60, 60, 60]), 8)).json()
    assert same["new_personal_records"] == []

    heavier = _post(api, headers, _workout(plan, BENCH, _sets([70], reps=8), 8)).json()
    assert [r["max_weight"] for r in heavier["new_personal_records"]] == [70.0]

    with _sync_engine().connect() as db:
        records = db.execute(
            text("SELECT max_weight, e1rm, is_current FROM personal_record ORDER BY id")
        ).all()
        notes = db.execute(
            text("SELECT message, data FROM notification WHERE message_type = 'achievement'")
        ).all()
    # e1RM 60 x 10 = 80.00, 70 x 8 = 88.67 (algorithms.md 6)
    assert [(float(w), float(e), c) for w, e, c in records] == [
        (60.0, 80.0, False),
        (70.0, 88.67, True),
    ]
    assert len(notes) == 2
    assert notes[0].message == "New personal record: Bench press, 60 kg x 10"
    assert notes[1].data["workout_log_id"] == heavier["workout"]["id"]


# ---------------------------------------------------------------- idempotency


def test_repeated_client_uuid_returns_the_first_answer_and_applies_nothing_twice(api):
    headers = _login(api)
    plan = _plan(1)
    body = _workout(plan, BENCH, _sets([60, 60, 60]), 6, client_uuid=str(uuid.uuid4()))

    first = _post(api, headers, body)
    again = _post(api, headers, body)

    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert first.json()["adjustments"] and first.json()["new_personal_records"]
    assert _count("workout_log") == 1
    assert _count("plan_adjustment") == 1
    assert _planned(plan[BENCH]) == (3, 10, 62.5)


def test_client_uuid_of_a_deleted_workout_or_another_user_is_409(api):
    ann = _login(api)
    bob = _login(api, "bob@example.com")
    plan = _plan(1)
    body = _workout(plan, BENCH, _sets([60]), 8, client_uuid=str(uuid.uuid4()))
    workout_id = _post(api, ann, body).json()["workout"]["id"]

    other = {
        **body,
        "training_session_id": None,
        "exercises": [{"exercise_id": BENCH, "sort_order": 1, "sets": _sets([60])}],
    }
    assert _post(api, bob, other).status_code == 409

    assert api.delete(f"/api/v1/workouts/{workout_id}", headers=ann).status_code == 204
    assert _post(api, ann, body).status_code == 409


# ---------------------------------------------------------------- validation and ownership


def test_another_users_session_is_unknown(api):
    _login(api)
    bob = _login(api, "bob@example.com")
    anns_plan = _plan(1)

    response = _post(api, bob, _workout(anns_plan, BENCH, _sets([60]), 8))

    assert response.status_code == 422
    assert response.json()["details"][0] == {
        "field": "body.training_session_id",
        "code": "not_found",
        "message": "Unknown session",
    }
    assert _planned(anns_plan[BENCH]) == (3, 10, 60.0)


@pytest.mark.parametrize(
    ("change", "field", "code"),
    [
        ({"log_date": "2999-01-01"}, "body.log_date", "future_date"),
        ({"exercise_id": 999}, "body.exercises.0.exercise_id", "not_found"),
        ({"session_exercise_id": 999}, "body.exercises.0.session_exercise_id", "outside_session"),
        ({"duplicate_set": True}, "body.exercises.0.sets.1.set_number", "duplicate"),
    ],
)
def test_invalid_workouts_are_422_and_store_nothing(api, change, field, code):
    headers = _login(api)
    plan = _plan(1)
    body = _workout(plan, BENCH, _sets([60, 60]), 8)
    exercise = body["exercises"][0]
    if "log_date" in change:
        body["log_date"] = change["log_date"]
    for key in ("exercise_id", "session_exercise_id"):
        if key in change:
            exercise[key] = change[key]
    if change.get("duplicate_set"):
        exercise["sets"][1]["set_number"] = 1

    response = _post(api, headers, body)

    assert response.status_code == 422
    assert (response.json()["details"][0]["field"], response.json()["details"][0]["code"]) == (
        field,
        code,
    )
    assert _count("workout_log") == 0


# ---------------------------------------------------------------- list, edit, delete


def test_history_is_newest_first_filtered_paginated_and_private(api):
    ann = _login(api)
    bob = _login(api, "bob@example.com")
    for day in (1, 3, 2):
        body = {
            "log_date": date(2026, 10, day).isoformat(),
            "rpe_rating": 7,
            "exercises": [{"exercise_id": BENCH, "sort_order": 1, "sets": _sets([50])}],
        }
        _post(api, ann, body)
    _post(api, bob, body)

    page = api.get("/api/v1/workouts", headers=ann, params={"limit": 2}).json()
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 0)
    assert [w["log_date"] for w in page["items"]] == ["2026-10-03", "2026-10-02"]

    ranged = api.get("/api/v1/workouts", headers=ann, params={"from": "2026-10-02"}).json()
    assert [w["log_date"] for w in ranged["items"]] == ["2026-10-03", "2026-10-02"]

    first_id = page["items"][0]["id"]
    assert api.delete(f"/api/v1/workouts/{first_id}", headers=ann).status_code == 204
    assert api.get("/api/v1/workouts", headers=ann).json()["total"] == 2
    assert api.get("/api/v1/workouts", headers=bob).json()["total"] == 1


def test_edit_keeps_the_uuid_and_does_not_adapt(api):
    headers = _login(api)
    plan = _plan(1)
    client_uuid = str(uuid.uuid4())
    created = _post(
        api, headers, _workout(plan, BENCH, _sets([60, 60, 60]), 8, client_uuid=client_uuid)
    )
    workout_id = created.json()["workout"]["id"]

    edited = api.put(
        f"/api/v1/workouts/{workout_id}",
        json=_workout(plan, BENCH, _sets([60, 60, 60]), 6, client_uuid=str(uuid.uuid4())),
        headers=headers,
    )

    assert edited.status_code == 200
    assert edited.json()["rpe_rating"] == 6
    assert _planned(plan[BENCH]) == (3, 10, 60.0)  # RPE 6 would progress, PUT never adapts
    assert _count("plan_adjustment") == 0
    with _sync_engine().connect() as db:
        stored = db.execute(text("SELECT client_uuid FROM workout_log")).scalar_one()
    assert str(stored) == client_uuid


def test_edit_and_delete_of_another_users_workout_are_404(api):
    ann = _login(api)
    bob = _login(api, "bob@example.com")
    body = {
        "log_date": TODAY.isoformat(),
        "rpe_rating": 7,
        "exercises": [{"exercise_id": BENCH, "sort_order": 1, "sets": _sets([50])}],
    }
    workout_id = _post(api, ann, body).json()["workout"]["id"]

    assert api.put(f"/api/v1/workouts/{workout_id}", json=body, headers=bob).status_code == 404
    assert api.delete(f"/api/v1/workouts/{workout_id}", headers=bob).status_code == 404
    assert api.delete(f"/api/v1/workouts/{workout_id}", headers=ann).status_code == 204
    assert api.delete(f"/api/v1/workouts/{workout_id}", headers=ann).status_code == 404


# ---------------------------------------------------------------- concurrency


def _service_workout(plan, client_uuid=None) -> WorkoutIn:
    sets = tuple(SetIn(n, 10, Decimal("60"), True, None) for n in (1, 2, 3))
    return WorkoutIn(
        client_uuid=client_uuid,
        training_session_id=plan[0],
        log_date=TODAY,
        rpe_rating=6,
        exercises=(ExerciseIn(BENCH, plan[BENCH], 1, sets),),
    )


def test_concurrent_workouts_of_one_session_adapt_from_the_locked_plan(api, sessions):
    _login(api)
    plan = _plan(1)
    _, factory = sessions
    service = WorkoutService(SqlWorkoutUnitOfWork(factory))

    async def both():
        now = datetime.now(UTC)
        return await asyncio.gather(
            service.create(1, "Europe/Warsaw", _service_workout(plan), now),
            service.create(1, "Europe/Warsaw", _service_workout(plan), now),
        )

    results = api.portal.call(both)

    # the second waits for the first's lock, then sees 62.5 and 60 kg is no reserve (vector K)
    assert sorted(len(r.adjustments) for r in results) == [0, 1]
    assert _planned(plan[BENCH]) == (3, 10, 62.5)


def test_concurrent_replays_of_one_client_uuid_store_one_workout(api, sessions):
    _login(api)
    plan = _plan(1)
    _, factory = sessions
    service = WorkoutService(SqlWorkoutUnitOfWork(factory))
    client_uuid = uuid.uuid4()

    async def both():
        now = datetime.now(UTC)
        return await asyncio.gather(
            service.create(1, "Europe/Warsaw", _service_workout(plan, client_uuid), now),
            service.create(1, "Europe/Warsaw", _service_workout(plan, client_uuid), now),
        )

    first, second = api.portal.call(both)

    assert first == second
    assert _count("workout_log") == 1
    assert _count("plan_adjustment") == 1
