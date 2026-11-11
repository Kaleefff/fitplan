"""Nutrition log endpoints and the daily summary on PostgreSQL (B-21).

The arithmetic and storage rules are DB-09's and tested in test_nutrition_logs.py;
these tests check the HTTP layer: status codes, error fields, dates in the user's
time zone, PATCH semantics and the summary against a real diet plan. Uses the
fixtures of the diet plan tests (the whole seed); skipped without PostgreSQL.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.db import test_diet_plans as diet
from tests.db.test_diet_plans import _generate, _login, _rows

api = diet.api
seeded = diet.seeded
migrated_db = diet.migrated_db
_close_sync_engine = diet._close_sync_engine

LOGS = "/api/v1/nutrition-logs"
SUMMARY = "/api/v1/nutrition/daily-summary"


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Warsaw")).date()  # the default app_user.timezone


def _foods(n: int = 2) -> list:
    return _rows(
        "SELECT id, name, cals_per_100g, protein_per_100g, fat_per_100g, carbs_per_100g"
        " FROM food_item WHERE is_active ORDER BY id LIMIT :n",
        n=n,
    )


def _body(foods, grams=(150, 80), **extra) -> dict:
    return {
        "log_date": _today().isoformat(),
        "meal_type": "lunch",
        "items": [{"food_item_id": f.id, "grams": g} for f, g in zip(foods, grams, strict=False)],
        **extra,
    }


def _rounded(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _detail(response) -> tuple[int, str, str]:
    body = response.json()
    return response.status_code, body["details"][0]["field"], body["details"][0]["code"]


# ---------------------------------------------------------------- create


def test_create_returns_the_log_with_totals_equal_to_the_sum_of_the_items(api):
    headers = _login(api, profile=None)
    foods = _foods()

    response = api.post(LOGS, json=_body(foods, hunger_level_before=7), headers=headers)

    assert response.status_code == 201, response.text
    log = response.json()
    expected = [
        sum(
            _rounded(Decimal(g) * getattr(f, column) / 100)
            for f, g in zip(foods, (150, 80), strict=True)
        )
        for column in ("cals_per_100g", "protein_per_100g", "fat_per_100g", "carbs_per_100g")
    ]
    totals = [log["actual_cals"], log["actual_protein"], log["actual_fat"], log["actual_carbs"]]
    assert totals == pytest.approx(expected, abs=1e-9)
    assert [i["food_item_id"] for i in log["items"]] == sorted(f.id for f in foods)
    assert (log["hunger_level_before"], log["hunger_level_after"]) == (7, None)
    assert log["planned_meal_id"] is None and uuid.UUID(log["client_uuid"])


def test_a_repeated_client_uuid_returns_the_first_log_and_a_deleted_one_is_409(api):
    headers = _login(api, profile=None)
    client_uuid = str(uuid.uuid4())
    body = _body(_foods(), client_uuid=client_uuid)

    first = api.post(LOGS, json=body, headers=headers)
    again = api.post(LOGS, json=body | {"meal_type": "dinner"}, headers=headers)

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert api.delete(f"{LOGS}/{first.json()['id']}", headers=headers).status_code == 204
    assert _detail(api.post(LOGS, json=body, headers=headers)) == (
        409,
        "body.client_uuid",
        "conflict",
    )


def test_the_date_may_be_at_most_tomorrow_in_the_users_time_zone(api):
    headers = _login(api, profile=None)
    foods = _foods()
    tomorrow, later = _today() + timedelta(days=1), _today() + timedelta(days=2)

    assert (
        api.post(
            LOGS, json=_body(foods, log_date=tomorrow.isoformat()), headers=headers
        ).status_code
        == 201
    )
    assert _detail(
        api.post(LOGS, json=_body(foods, log_date=later.isoformat()), headers=headers)
    ) == (
        422,
        "body.log_date",
        "future_date",
    )


@pytest.mark.parametrize(
    ("change", "field", "code"),
    [
        ("duplicate", "body.items.1.food_item_id", "duplicate"),
        ("unknown", "body.items.0.food_item_id", "not_found"),
        ("zero", "body.items.0.grams", "invalid_value"),
        ("huge", "body.items", "too_large"),
        ("hunger", "body.hunger_level_after", None),
    ],
)
def test_invalid_logs_are_422_with_the_field(api, change, field, code):
    headers = _login(api, profile=None)
    foods = _foods()
    body = _body(foods)
    if change == "duplicate":
        body["items"][1]["food_item_id"] = foods[0].id
    elif change == "unknown":
        body["items"][0]["food_item_id"] = 999999
    elif change == "zero":
        body["items"][0]["grams"] = 0.04
    elif change == "huge":
        fattest = _rows(
            "SELECT id FROM food_item WHERE is_active ORDER BY cals_per_100g DESC LIMIT 1"
        )
        body["items"] = [{"food_item_id": fattest[0].id, "grams": 99999.9}]
    else:
        body["hunger_level_after"] = 11

    response = api.post(LOGS, json=body, headers=headers)

    assert response.status_code == 422
    detail = response.json()["details"][0]
    assert detail["field"] == field
    if code is not None:
        assert detail["code"] == code
    assert api.get(LOGS, headers=headers).json()["total"] == 0


def test_an_inactive_food_cannot_be_logged(api):
    headers = _login(api, profile=None)
    food = _foods(1)[0]
    with diet._sync_engine().begin() as db:
        db.exec_driver_sql("UPDATE food_item SET is_active = false WHERE id = %s", (food.id,))
    try:
        response = api.post(LOGS, json=_body([food], grams=(100,)), headers=headers)
    finally:
        with diet._sync_engine().begin() as db:
            db.exec_driver_sql("UPDATE food_item SET is_active = true WHERE id = %s", (food.id,))

    assert _detail(response) == (422, "body.items.0.food_item_id", "not_found")


# ---------------------------------------------------------------- read, patch, delete


def test_history_is_newest_first_and_filtered_by_date(api):
    headers = _login(api, profile=None)
    foods = _foods()
    for days_ago in (2, 0, 1):
        day = (_today() - timedelta(days=days_ago)).isoformat()
        api.post(LOGS, json=_body(foods, log_date=day), headers=headers)

    page = api.get(f"{LOGS}?limit=2", headers=headers).json()
    since = (_today() - timedelta(days=1)).isoformat()
    filtered = api.get(LOGS, params={"from": since}, headers=headers).json()

    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 0)
    assert [log["log_date"] for log in page["items"]] == [
        _today().isoformat(),
        (_today() - timedelta(days=1)).isoformat(),
    ]
    assert filtered["total"] == 2


def test_patch_changes_sent_fields_clears_nulls_and_replaces_items(api):
    headers = _login(api, profile=None)
    foods = _foods(3)
    log = api.post(LOGS, json=_body(foods[:2], hunger_level_before=5), headers=headers).json()

    patched = api.patch(
        f"{LOGS}/{log['id']}",
        json={
            "meal_type": "dinner",
            "hunger_level_before": None,
            "items": [{"food_item_id": foods[2].id, "grams": 100}],
        },
        headers=headers,
    )

    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert (body["meal_type"], body["hunger_level_before"]) == ("dinner", None)
    assert [i["food_item_id"] for i in body["items"]] == [foods[2].id]
    assert body["actual_cals"] == _rounded(foods[2].cals_per_100g)
    assert (body["client_uuid"], body["log_date"]) == (log["client_uuid"], log["log_date"])


@pytest.mark.parametrize("body", [{}, {"log_date": None}, {"items": []}, {"meal_type": None}])
def test_an_empty_or_null_patch_is_422(api, body):
    headers = _login(api, profile=None)
    log = api.post(LOGS, json=_body(_foods()), headers=headers).json()

    assert api.patch(f"{LOGS}/{log['id']}", json=body, headers=headers).status_code == 422


def test_another_users_or_a_deleted_log_is_404(api):
    ann = _login(api, profile=None)
    log = api.post(LOGS, json=_body(_foods()), headers=ann).json()
    bob = _login(api, profile=None, email="bob@example.com")

    assert (
        api.patch(f"{LOGS}/{log['id']}", json={"meal_type": "snack"}, headers=bob).status_code
        == 404
    )
    assert api.delete(f"{LOGS}/{log['id']}", headers=bob).status_code == 404
    assert api.delete(f"{LOGS}/{log['id']}", headers=ann).status_code == 204
    assert api.delete(f"{LOGS}/{log['id']}", headers=ann).status_code == 404
    assert (
        api.patch(f"{LOGS}/{log['id']}", json={"meal_type": "snack"}, headers=ann).status_code
        == 404
    )
    assert api.get(LOGS, headers=ann).json()["total"] == 0


# ---------------------------------------------------------------- daily summary


def test_summary_without_a_plan_has_no_targets_and_defaults_to_today(api):
    headers = _login(api, profile=None)
    api.post(LOGS, json=_body(_foods(), hunger_level_before=4), headers=headers)
    api.post(LOGS, json=_body(_foods(), hunger_level_before=5, meal_type="dinner"), headers=headers)

    summary = api.get(SUMMARY, headers=headers).json()

    assert summary["date"] == _today().isoformat()
    assert (summary["targets"], summary["remaining"]) == (None, None)
    assert (summary["avg_hunger_before"], summary["avg_hunger_after"]) == (4.5, None)
    assert [log["meal_type"] for log in summary["logs"]] == ["lunch", "dinner"]  # by id
    assert summary["totals"]["kcal"] == pytest.approx(
        sum(log["actual_cals"] for log in summary["logs"])
    )


def test_summary_against_the_active_plan_and_a_planned_meal(api):
    headers = _login(api)
    plan = _generate(api, headers).json()
    api.post(f"/api/v1/diet-plans/{plan['id']}/accept", headers=headers)
    meal = plan["meals"][0]
    body = {
        "log_date": _today().isoformat(),
        "meal_type": meal["meal_type"],
        "planned_meal_id": meal["id"],
        "hunger_level_before": 3,
        "hunger_level_after": 4,
        "items": [{"food_item_id": i["food_item_id"], "grams": i["grams"]} for i in meal["items"]],
    }
    for hunger in (3, 4, 4):  # averages 3.666… → 3.7 (half up to one decimal)
        log = api.post(LOGS, json=body | {"hunger_level_before": hunger}, headers=headers)
        assert log.status_code == 201, log.text
    assert log.json()["planned_meal_id"] == meal["id"]

    summary = api.get(SUMMARY, params={"date": _today().isoformat()}, headers=headers).json()

    targets, totals, remaining = summary["targets"], summary["totals"], summary["remaining"]
    assert targets["kcal"] == plan["daily_cal_goal"]
    for key in ("kcal", "protein", "fat", "carbs"):
        assert remaining[key] == pytest.approx(targets[key] - totals[key])
    assert (summary["avg_hunger_before"], summary["avg_hunger_after"]) == (3.7, 4.0)


def test_another_users_planned_meal_is_422(api):
    ann = _login(api)
    meal = _generate(api, ann).json()["meals"][0]
    bob = _login(api, profile=None, email="bob@example.com")

    response = api.post(LOGS, json=_body(_foods(), planned_meal_id=meal["id"]), headers=bob)

    assert _detail(response) == (422, "body.planned_meal_id", "not_found")


def test_a_token_is_required(api):
    assert api.get(LOGS).status_code == 401
    assert api.get(SUMMARY).status_code == 401
