"""Meal suggestions on PostgreSQL with the whole seed (B-22; FR-N5, algorithms.md 10).

The formulas are tested in tests/domain/test_suggestions.py; these tests check the
endpoint against a real active diet plan and today's logs. Uses the fixtures of the
diet plan tests; skipped without PostgreSQL.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.db import test_diet_plans as diet
from tests.db.test_diet_plans import _generate, _login, _rows

api = diet.api
seeded = diet.seeded
migrated_db = diet.migrated_db
_close_sync_engine = diet._close_sync_engine

SUGGESTIONS = "/api/v1/nutrition/suggestions"


def _today() -> str:
    return datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat()  # default time zone


def _active_plan(api, headers) -> dict:
    plan = _generate(api, headers).json()
    response = api.post(f"/api/v1/diet-plans/{plan['id']}/accept", headers=headers)
    assert response.status_code == 200, response.text
    return api.get("/api/v1/diet-plans/active", headers=headers).json()


def _log(api, headers, items, planned_meal_id=None):
    response = api.post(
        "/api/v1/nutrition-logs",
        json={
            "client_uuid": str(uuid.uuid4()),
            "log_date": _today(),
            "meal_type": "lunch",
            "planned_meal_id": planned_meal_id,
            "items": items,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def _suggestions(api, headers) -> dict:
    response = api.get(SUGGESTIONS, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_without_an_active_diet_plan_is_404(api):
    headers = _login(api)
    _generate(api, headers)  # a draft is not enough

    assert api.get(SUGGESTIONS, headers=headers).status_code == 404


def test_suggestions_fit_the_remaining_kcal_and_today_of_the_plan(api):
    headers = _login(api)
    plan = _active_plan(api, headers)
    today_meals = {m["id"]: m for m in plan["meals"] if m["day_index"] == 1}  # started today

    body = _suggestions(api, headers)

    assert body["status"] == "ok"
    assert body["remaining"]["kcal"] == plan["daily_cal_goal"]
    assert 1 <= len(body["suggestions"]) <= 5
    for suggestion in body["suggestions"]:
        assert suggestion["nutrition"]["kcal"] <= body["remaining"]["kcal"] * 1.05
        if suggestion["kind"] == "planned_meal":
            assert suggestion["meal_id"] in today_meals
            assert suggestion["food_item_id"] is None
        else:
            assert suggestion["meal_id"] is None


def test_a_logged_planned_meal_and_allergens_are_not_suggested(api):
    headers = _login(api)
    plan = _active_plan(api, headers)
    first = next(m for m in plan["meals"] if m["day_index"] == 1)
    _log(
        api,
        headers,
        [{"food_item_id": i["food_item_id"], "grams": i["grams"]} for i in first["items"]],
        planned_meal_id=first["id"],
    )
    milk = _rows("SELECT id FROM allergen WHERE name = 'Milk'")[0][0]
    api.put("/api/v1/users/me/allergies", json={"allergen_ids": [milk]}, headers=headers)
    with_milk = {
        row[0]
        for row in _rows(
            "SELECT food_item_id FROM food_item_allergen WHERE allergen_id = :a", a=milk
        )
    }
    meal_foods = {m["id"]: {i["food_item_id"] for i in m["items"]} for m in plan["meals"]}

    body = _suggestions(api, headers)

    assert body["remaining"]["kcal"] < plan["daily_cal_goal"]
    for suggestion in body["suggestions"]:
        assert suggestion["meal_id"] != first["id"]
        foods = meal_foods.get(suggestion["meal_id"], {suggestion["food_item_id"]})
        assert not foods & with_milk


def test_a_reached_target_gives_no_suggestions_and_zero_remaining(api):
    headers = _login(api)
    plan = _active_plan(api, headers)
    food_id, kcal = _rows(
        "SELECT id, cals_per_100g FROM food_item WHERE is_active"
        " ORDER BY cals_per_100g DESC, id LIMIT 1"
    )[0]
    _log(
        api,
        headers,
        [{"food_item_id": food_id, "grams": round(plan["daily_cal_goal"] / float(kcal) * 110)}],
    )

    body = _suggestions(api, headers)

    assert (body["status"], body["suggestions"], body["remaining"]["kcal"]) == (
        "target_reached",
        [],
        0,
    )
    assert min(body["remaining"].values()) >= 0
