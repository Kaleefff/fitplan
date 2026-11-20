"""Progress report endpoints on PostgreSQL (B-25; FR-R1, FR-R5).

Done of B-25: a report's figures equal the analytics of the same period. Uses the
DB-10 fixture week of the analytics tests; skipped without PostgreSQL.
"""

from datetime import timedelta

from tests.db import test_analytics_queries as analytics
from tests.db.test_analytics_queries import TODAY, _fixture_week, _login, _weigh_in, day

api = analytics.api
migrated_db = analytics.migrated_db
_close_sync_engine = analytics._close_sync_engine

REPORTS = "/api/v1/reports"


def _generate(api, headers, start, end):
    return api.post(
        REPORTS,
        json={"period_start": start.isoformat(), "period_end": end.isoformat()},
        headers=headers,
    )


def test_a_report_equals_the_analytics_of_the_same_period(api):
    headers = _login(api)
    _fixture_week(1)
    summary = api.get(
        "/api/v1/analytics/summary", params={"period": "week"}, headers=headers
    ).json()
    prediction = api.get("/api/v1/analytics/goal-prediction", headers=headers).json()

    response = _generate(api, headers, day(6), TODAY)

    assert response.status_code == 201, response.text
    report = response.json()
    assert (report["report_period_start"], report["report_period_end"]) == (
        summary["period_start"],
        summary["period_end"],
    )
    assert {
        "weight_difference": report["weight_difference"],
        "training_volume": report["training_volume"],
        "training_sessions_completed": report["training_sessions_completed"],
        "workout_compliance_pct": report["workout_compliance_pct"],
        "diet_compliance_pct": report["diet_compliance_pct"],
        "avg_cals_daily": report["avg_cals_daily"],
        "key_lifts": report["key_lifts"],
    } == {
        "weight_difference": summary["weight_change"],
        "training_volume": summary["tonnage"],
        "training_sessions_completed": summary["total_workouts"],
        "workout_compliance_pct": summary["workout_compliance_pct"],
        "diet_compliance_pct": summary["diet_compliance_pct"],
        "avg_cals_daily": summary["avg_calories"],
        "key_lifts": summary["key_lifts"],
    }
    # 3 sessions a week over the 6 covered days: 2.57 planned, rounded
    assert report["training_sessions_planned"] == 3
    assert (report["estimated_goal_completion_date"], report["irregular_data"]) == (
        prediction["estimated_date"],
        prediction["irregular_data"],
    )
    assert report["is_auto"] is False
    assert report["report_type"] == ("weekly" if day(6).weekday() == 0 else "custom")


def test_the_same_period_again_replaces_the_report(api):
    headers = _login(api)
    _fixture_week(1)
    first = _generate(api, headers, day(6), TODAY).json()
    _weigh_in(1, 0, 79.0)

    again = _generate(api, headers, day(6), TODAY).json()
    page = api.get(REPORTS, headers=headers).json()

    assert again["id"] == first["id"]
    assert (first["weight_difference"], again["weight_difference"]) == (-0.6, -1.0)
    assert (page["total"], [r["id"] for r in page["items"]]) == (1, [first["id"]])
    assert api.get(f"{REPORTS}/{first['id']}", headers=headers).json() == again


def test_reports_are_listed_newest_first_and_other_users_get_404(api):
    headers = _login(api)
    _fixture_week(1)
    older = _generate(api, headers, day(6), day(3)).json()
    newer = _generate(api, headers, day(2), TODAY).json()
    bob = _login(api, "bob@example.com")

    page = api.get(REPORTS, params={"limit": 1}, headers=headers).json()

    assert (page["total"], [r["id"] for r in page["items"]]) == (2, [newer["id"]])
    assert api.get(f"{REPORTS}/{older['id']}", headers=bob).status_code == 404
    assert api.get(REPORTS, headers=bob).json()["total"] == 0


def test_fewer_than_7_days_of_history_is_insufficient_data(api):
    headers = _login(api)
    for days_ago in range(6):
        _weigh_in(1, days_ago, 80)

    response = _generate(api, headers, day(6), TODAY)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "insufficient_data"
    assert api.get(REPORTS, headers=headers).json()["total"] == 0


def test_invalid_periods_are_422(api):
    headers = _login(api)
    _fixture_week(1)

    for start, end in (
        (TODAY, day(1)),  # end before start
        (day(366), TODAY),  # 367 days
        (day(1), TODAY + timedelta(days=1)),  # after today
    ):
        response = _generate(api, headers, start, end)
        assert response.status_code == 422, response.text
        assert [d["field"] for d in response.json()["details"]] == ["body.period_end"]
