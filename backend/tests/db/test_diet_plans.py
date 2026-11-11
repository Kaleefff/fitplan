"""Diet plans on PostgreSQL with the reference seed (B-12).

Loads the seed of app.db.seed (DB-02, DB-03, DB-04), so the coverage test runs the
generator over DB-04's foods; skipped without PostgreSQL.
"""

import functools
import time
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.analytics import SqlAnalyticsUnitOfWork
from app.db.repositories.body_metrics import SqlBodyMetricsUnitOfWork
from app.db.repositories.diet_plans import SqlDietPlanUnitOfWork
from app.db.repositories.library import SqlLibraryRepository
from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.schedule import SqlScheduleUnitOfWork
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.seed import load
from app.db.session import database_url
from app.domain.constants import DAY_TOLERANCES, DietType, Goal
from app.main import create_app
from app.services.repositories import Repositories
from tests.clock import today
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

TODAY = today()
PROFILES = {
    "male": {
        "age": 25,
        "sex": "male",
        "current_weight": 80,
        "height": 180,
        "activity_level_pal": 1.55,
    },
    "female": {
        "age": 30,
        "sex": "female",
        "current_weight": 60,
        "height": 165,
        "activity_level_pal": 1.375,
    },
}
TIMINGS: list[float] = []


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


def _rows(sql: str, **params) -> list:
    with _sync_engine().connect() as db:
        return db.execute(text(sql), params).all()


@pytest.fixture(scope="module")
def seeded(migrated_db):  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "TRUNCATE app_user, muscle_group, injury_type, allergen, food_category, food_item"
                " RESTART IDENTITY CASCADE"
            )
        )
        load(db)


@pytest.fixture
def api(seeded) -> Iterator[TestClient]:
    with _sync_engine().begin() as db:
        db.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
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
    )
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), repositories=repositories
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(engine.dispose)


def _login(api, goal="maintenance", profile="male", email="ann@example.com") -> dict[str, str]:
    pair = api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "name": "A", "surname": "B"},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}
    if profile:
        api.put(
            "/api/v1/users/me/profile",
            json={
                **PROFILES[profile],
                "goal": goal,
                "experience_level": "beginner",
                "equipment": "gym",
            },
            headers=headers,
        )
    return headers


def _generate(api, headers, meals=4, diet="omnivore", **extra):
    started = time.perf_counter()
    response = api.post(
        "/api/v1/diet-plans/generate",
        json={"meals_per_day": meals, "diet_type": diet, **extra},
        headers=headers,
    )
    TIMINGS.append(time.perf_counter() - started)
    return response


def _day_totals(plan_id: int) -> dict[int, list[float]]:
    """Recomputed from the stored grams and the food values, not from the plan."""
    totals = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for day, grams, kcal, protein, fat, carbs in _rows(
        "SELECT m.day_index, i.grams, f.cals_per_100g, f.protein_per_100g, f.fat_per_100g,"
        " f.carbs_per_100g FROM meal m JOIN meal_food_item i ON i.meal_id = m.id"
        " JOIN food_item f ON f.id = i.food_item_id WHERE m.diet_plan_id = :p",
        p=plan_id,
    ):
        for k, value in enumerate((kcal, protein, fat, carbs)):
            totals[day][k] += float(grams) * float(value) / 100
    return totals


# ---------------------------------------------------------------- Done of B-12


@pytest.mark.parametrize("meals", [3, 4, 5])
@pytest.mark.parametrize("diet", [d.value for d in DietType])
@pytest.mark.parametrize("goal", [g.value for g in Goal])
def test_every_goal_diet_and_meal_count_passes_the_tolerances(api, goal, diet, meals):
    headers = _login(api, goal=goal, profile="female" if goal == "weight_loss" else "male")

    response = _generate(api, headers, meals=meals, diet=diet)

    assert response.status_code == 201, response.json()
    plan = response.json()
    assert (plan["status"], plan["diet_type"], plan["meals_per_day"]) == ("draft", diet, meals)
    assert len(plan["meals"]) == 7 * meals
    targets = (plan["daily_cal_goal"], plan["protein_goal"], plan["fat_goal"], plan["carbs_goal"])
    days = _day_totals(plan["id"])
    assert sorted(days) == list(range(1, 8))
    for day, totals in days.items():
        for actual, target, tolerance in zip(totals, targets, DAY_TOLERANCES, strict=True):
            assert abs(actual - target) / target <= tolerance, (day, totals, targets)
    if diet != "omnivore":
        flag = "is_vegan" if diet == "vegan" else "is_vegetarian"
        bad = _rows(
            "SELECT count(*) FROM meal m JOIN meal_food_item i ON i.meal_id = m.id"
            " JOIN food_item f ON f.id = i.food_item_id"
            f" WHERE m.diet_plan_id = :p AND NOT f.{flag}",
            p=plan["id"],
        )
        assert bad[0][0] == 0


def test_generation_time_p95_under_3_seconds(seeded):
    """Runs after the 54 plans above (pytest keeps file order)."""
    if not TIMINGS:
        pytest.skip("needs the coverage test above in the same run")
    ordered = sorted(TIMINGS)
    assert ordered[int(0.95 * (len(ordered) - 1))] < 3.0


def test_allergens_and_excluded_foods_are_never_selected(api):
    headers = _login(api)
    milk, peanuts = (
        _rows("SELECT id FROM allergen WHERE name = :n", n=name)[0][0]
        for name in ("Milk", "Peanuts")
    )
    rice = _rows("SELECT id FROM food_item WHERE name = 'White rice, cooked'")[0][0]
    api.put("/api/v1/users/me/allergies", json={"allergen_ids": [milk, peanuts]}, headers=headers)
    api.put("/api/v1/users/me/excluded-foods", json={"food_item_ids": [rice]}, headers=headers)

    plan = _generate(api, headers, meals=5).json()

    chosen = {item["food_item_id"] for meal in plan["meals"] for item in meal["items"]}
    assert rice not in chosen
    with_allergen = _rows(
        "SELECT DISTINCT food_item_id FROM food_item_allergen WHERE allergen_id IN (:a, :b)",
        a=milk,
        b=peanuts,
    )
    assert not chosen & {row[0] for row in with_allergen}


def test_gluten_allergy_is_planned_from_gluten_free_foods(api):
    """DB-04 has gluten-free breakfast carbs, so a gluten allergy still gets a plan."""
    headers = _login(api)
    gluten = _rows("SELECT id FROM allergen WHERE name = 'Gluten'")[0][0]
    api.put("/api/v1/users/me/allergies", json={"allergen_ids": [gluten]}, headers=headers)

    response = _generate(api, headers)

    assert response.status_code == 201, response.json()
    chosen = {item["food_item_id"] for meal in response.json()["meals"] for item in meal["items"]}
    with_gluten = _rows(
        "SELECT food_item_id FROM food_item_allergen WHERE allergen_id = :a", a=gluten
    )
    assert not chosen & {row[0] for row in with_gluten}


# ---------------------------------------------------------------- errors and lifecycle


def test_without_a_profile_is_404(api):
    headers = _login(api, profile=None)
    assert _generate(api, headers).status_code == 404


def test_an_unfillable_role_is_422_and_keeps_the_draft(api):
    headers = _login(api)
    draft = _generate(api, headers).json()
    fruits = [row[0] for row in _rows("SELECT id FROM food_item WHERE diet_role = 'fruit'")]
    api.put("/api/v1/users/me/excluded-foods", json={"food_item_ids": fruits}, headers=headers)

    response = _generate(api, headers, meals=3)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "insufficient_foods"
    assert body["details"] == [
        {"field": "food", "code": "no_eligible_food", "meal_type": "breakfast", "role": "fruit"}
    ]
    assert api.get(f"/api/v1/diet-plans/{draft['id']}", headers=headers).status_code == 200


def test_generate_replace_accept_archive(api):
    headers = _login(api)
    assert api.get("/api/v1/diet-plans/active", headers=headers).status_code == 404
    first = _generate(api, headers, dietary_restrictions="no spicy food").json()
    assert first["dietary_restrictions"] == "no spicy food"
    assert first["name"] == "Maintenance diet, 4 meals"
    second = _generate(api, headers, meals=3, diet="vegan").json()
    assert second["name"] == "Maintenance vegan diet, 3 meals"
    assert api.get(f"/api/v1/diet-plans/{first['id']}", headers=headers).status_code == 404

    accepted = api.post(f"/api/v1/diet-plans/{second['id']}/accept", headers=headers).json()
    assert (accepted["status"], accepted["start_date"], accepted["end_date"]) == (
        "active",
        TODAY.isoformat(),
        (TODAY + timedelta(56)).isoformat(),
    )
    assert api.post(f"/api/v1/diet-plans/{second['id']}/accept", headers=headers).status_code == 409

    third = _generate(api, headers).json()
    api.post(f"/api/v1/diet-plans/{third['id']}/accept", headers=headers)
    assert (
        api.get(f"/api/v1/diet-plans/{second['id']}", headers=headers).json()["status"]
        == "archived"
    )
    assert api.get("/api/v1/diet-plans/active", headers=headers).json()["id"] == third["id"]

    bob = _login(api, email="bob@example.com")
    assert api.get(f"/api/v1/diet-plans/{third['id']}", headers=bob).status_code == 404
    assert api.get("/api/v1/diet-plans/generate", headers=headers).status_code == 405
