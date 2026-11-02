"""Profile, injuries, allergies, excluded foods, reference lists on PostgreSQL (B-06).

The reference rows come from the DB-02 seed; skipped without PostgreSQL.
"""

import functools
from collections.abc import Iterator
from datetime import date, timedelta

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
from app.db.seed import load
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

TODAY = date.today()
PROFILE = {
    "age": 25,
    "sex": "male",
    "current_weight": 80,
    "height": 180,
    "activity_level_pal": 1.55,
    "goal": "muscle_gain",
    "experience_level": "beginner",
    "equipment": "gym",
    "target_value": 85,
}


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


def _id(sql: str, **params) -> int:
    with _sync_engine().connect() as db:
        return db.execute(text(sql), params).scalar_one()


@pytest.fixture
def api(migrated_db) -> Iterator[TestClient]:  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, injury_type, allergen, food_category, food_item"
                " RESTART IDENTITY CASCADE"
            )
        )
        load(db)
    engine = create_async_engine(database_url().set(database=TEST_DB))
    factory = async_sessionmaker(engine, expire_on_commit=False)
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


# ---------------------------------------------------------------- profile


def test_profile_round_trip_and_tdee(api):
    headers = _login(api)
    assert api.get("/api/v1/users/me/profile", headers=headers).status_code == 404

    saved = api.put("/api/v1/users/me/profile", json=PROFILE, headers=headers)

    assert saved.status_code == 200
    body = saved.json()
    # algorithms.md 2, vector 1: male 80 kg, 180 cm, 25 y, PAL 1.55 -> TDEE 2798
    assert body["tdee"] == 2798
    assert {k: body[k] for k in PROFILE} == {
        **PROFILE,
        "current_weight": 80.0,
        "target_value": 85.0,
    }
    assert api.get("/api/v1/users/me/profile", headers=headers).json() == body


def test_saving_again_recomputes_tdee_and_feeds_the_targets(api):
    headers = _login(api)
    first = api.put("/api/v1/users/me/profile", json=PROFILE, headers=headers).json()

    lighter = api.put(
        "/api/v1/users/me/profile",
        json={**PROFILE, "current_weight": 70.555, "target_value": None},
        headers=headers,
    ).json()

    assert lighter["current_weight"] == 70.56  # rounded half up to 2 decimals
    assert lighter["target_value"] is None
    assert lighter["tdee"] < first["tdee"]
    assert lighter["profile_update"] >= first["profile_update"]
    targets = api.get("/api/v1/nutrition/targets", headers=headers).json()
    assert targets["tdee"] == lighter["tdee"]


@pytest.mark.parametrize(
    ("field", "valid", "invalid"),
    [
        ("current_weight", [30, 300], [29, 301, 29.99, 300.01]),
        ("target_value", [30, 300, None], [29, 301]),
        ("age", [16, 100], [15, 101]),
        ("height", [120, 250], [119, 251]),
        ("activity_level_pal", [1.2, 1.9], [1.3, 2.5]),
    ],
)
def test_boundaries(api, field, valid, invalid):
    headers = _login(api)
    for value in valid:
        response = api.put(
            "/api/v1/users/me/profile", json={**PROFILE, field: value}, headers=headers
        )
        assert response.status_code == 200, (field, value)
    for value in invalid:
        response = api.put(
            "/api/v1/users/me/profile", json={**PROFILE, field: value}, headers=headers
        )
        assert response.status_code == 422, (field, value)
        assert [d["field"] for d in response.json()["details"]] == [f"body.{field}"]


def test_one_error_per_missing_or_invalid_field(api):
    headers = _login(api)
    response = api.put(
        "/api/v1/users/me/profile",
        json={"age": 12, "sex": "robot", "height": 300},
        headers=headers,
    )

    assert response.status_code == 422
    fields = sorted(d["field"] for d in response.json()["details"])
    assert fields == sorted(
        f"body.{f}"
        for f in [
            "age",
            "sex",
            "height",
            "current_weight",
            "activity_level_pal",
            "goal",
            "experience_level",
            "equipment",
        ]
    )


# ---------------------------------------------------------------- injuries


def _injury(api, headers, start=None, active=True, type_name="Knee pain", group="quadriceps"):
    return api.post(
        "/api/v1/users/me/injuries",
        json={
            "injury_type_id": _id("SELECT id FROM injury_type WHERE type_name = :n", n=type_name),
            "affected_muscle_group_id": _id(
                "SELECT id FROM muscle_group WHERE group_name = :n", n=group
            ),
            "severity": "moderate",
            "start_date": (start or TODAY).isoformat(),
            "is_active": active,
        },
        headers=headers,
    )


def test_injuries_are_listed_active_first_then_newest(api):
    headers = _login(api)
    old = _injury(api, headers, start=TODAY - timedelta(30)).json()
    new = _injury(api, headers, start=TODAY - timedelta(1)).json()
    healed = _injury(api, headers, start=TODAY, active=False).json()

    listed = api.get("/api/v1/users/me/injuries", headers=headers).json()

    assert [i["id"] for i in listed] == [new["id"], old["id"], healed["id"]]
    assert old["severity"] == "moderate" and old["is_active"] is True


def test_injury_validation(api):
    headers = _login(api)
    future = _injury(api, headers, start=TODAY + timedelta(2))
    assert future.status_code == 422
    assert future.json()["details"][0]["code"] == "future_date"

    unknown = api.post(
        "/api/v1/users/me/injuries",
        json={
            "injury_type_id": 9999,
            "affected_muscle_group_id": 1,
            "severity": "mild",
            "start_date": TODAY.isoformat(),
        },
        headers=headers,
    )
    assert unknown.status_code == 422
    assert unknown.json()["details"][0]["field"] == "body.injury_type_id"
    assert api.get("/api/v1/users/me/injuries", headers=headers).json() == []


def test_patch_and_delete_an_injury(api):
    headers = _login(api)
    injury = _injury(api, headers).json()
    url = f"/api/v1/users/me/injuries/{injury['id']}"

    healed = api.patch(url, json={"is_active": False}, headers=headers)
    assert healed.status_code == 200
    assert {**injury, "is_active": False} == healed.json()

    assert api.patch(url, json={}, headers=headers).status_code == 422
    assert api.patch(url, json={"severity": None}, headers=headers).status_code == 422

    bob = _login(api, "bob@example.com")
    assert api.patch(url, json={"is_active": True}, headers=bob).status_code == 404
    assert api.delete(url, headers=bob).status_code == 404

    assert api.delete(url, headers=headers).status_code == 204
    assert api.delete(url, headers=headers).status_code == 404


# ---------------------------------------------------------------- allergies, excluded foods


def test_allergies_are_replaced_with_duplicates_dropped(api):
    headers = _login(api)
    milk = _id("SELECT id FROM allergen WHERE name ILIKE 'milk%' ORDER BY id LIMIT 1")
    peanuts = _id("SELECT id FROM allergen WHERE name ILIKE 'peanut%' ORDER BY id LIMIT 1")

    saved = api.put(
        "/api/v1/users/me/allergies",
        json={"allergen_ids": [peanuts, milk, peanuts]},
        headers=headers,
    )

    assert saved.status_code == 200
    assert sorted(a["id"] for a in saved.json()) == sorted([milk, peanuts])
    assert [a["name"] for a in saved.json()] == sorted(a["name"] for a in saved.json())

    unknown = api.put(
        "/api/v1/users/me/allergies", json={"allergen_ids": [milk, 9999]}, headers=headers
    )
    assert unknown.status_code == 422
    assert unknown.json()["details"][0]["code"] == "not_found"
    assert len(api.get("/api/v1/users/me/allergies", headers=headers).json()) == 2

    cleared = api.put("/api/v1/users/me/allergies", json={"allergen_ids": []}, headers=headers)
    assert cleared.json() == []


def test_excluded_foods(api):
    headers = _login(api)
    with _sync_engine().begin() as db:  # no food seed before DB-04
        db.execute(
            text(
                "INSERT INTO food_item (name, cals_per_100g, protein_per_100g, fat_per_100g,"
                " carbs_per_100g, diet_role, suitable_meal_types, default_portion_g,"
                " min_portion_g, max_portion_g, portion_step_g, is_active) VALUES"
                " ('Broccoli', 34, 2.8, 0.4, 7, 'vegetable', '{lunch,dinner}', 100, 50, 300,"
                "  50, true),"
                " ('Old item', 50, 1, 1, 10, 'vegetable', '{lunch}', 100, 50, 300, 50, false)"
            )
        )
        db.execute(
            text(
                "INSERT INTO food_item_category (food_item_id, food_category_id)"
                " SELECT f.id, c.id FROM food_item f, (SELECT id FROM food_category"
                " ORDER BY id LIMIT 1) c WHERE f.name = 'Broccoli'"
            )
        )
    broccoli = _id("SELECT id FROM food_item WHERE name = 'Broccoli'")
    inactive = _id("SELECT id FROM food_item WHERE name = 'Old item'")

    saved = api.put(
        "/api/v1/users/me/excluded-foods",
        json={"food_item_ids": [broccoli, broccoli]},
        headers=headers,
    )
    assert saved.status_code == 200
    assert [(f["name"], f["cals_per_100g"], len(f["category_ids"])) for f in saved.json()] == [
        ("Broccoli", 34.0, 1)
    ]

    rejected = api.put(
        "/api/v1/users/me/excluded-foods", json={"food_item_ids": [inactive]}, headers=headers
    )
    assert rejected.status_code == 422
    assert [
        f["id"] for f in api.get("/api/v1/users/me/excluded-foods", headers=headers).json()
    ] == [broccoli]


# ---------------------------------------------------------------- reference lists


def test_reference_lists_come_from_the_seed_ordered_by_name(api):
    headers = _login(api)
    groups = api.get("/api/v1/muscle-groups", headers=headers).json()
    types = api.get("/api/v1/injury-types", headers=headers).json()
    allergens = api.get("/api/v1/allergens", headers=headers).json()

    assert len(groups) == 10
    assert [g["group_name"] for g in groups] == sorted(g["group_name"] for g in groups)
    assert [g["group_name"] for g in groups[:3]] == ["back", "biceps", "calves"]
    assert len(types) == _id("SELECT count(*) FROM injury_type") > 0
    assert all(t["avg_healing_time_days"] > 0 for t in types)
    assert [a["name"] for a in allergens] == sorted(a["name"] for a in allergens)
    assert api.get("/api/v1/allergens").status_code == 401
