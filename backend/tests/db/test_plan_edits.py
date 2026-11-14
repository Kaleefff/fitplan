"""Swap and plan edits on PostgreSQL with the reference seed (B-13; FR-A1, 4.9).

Uses the fixtures of the training plan tests; skipped without PostgreSQL.
"""

from sqlalchemy import text

from tests.db import test_training_plans as plans
from tests.db.test_training_plans import _generate, _login, _scalar, _sync_engine

api = plans.api
sessions = plans.sessions
migrated_db = plans.migrated_db
_close_sync_engine = plans._close_sync_engine

EDIT = "/api/v1/session-exercises/{}"
SWAP = "/api/v1/session-exercises/{}/swap"


def _plan(api, headers, **params) -> dict:
    response = _generate(api, headers, **({"goal": "muscle_gain", "days": 3} | params))
    assert response.status_code == 201, response.text
    return response.json()


def _slot(plan) -> tuple[dict, list[dict]]:
    """The first session exercise of the plan and its session's exercises."""
    session = plan["sessions"][0]
    return session["exercises"][0], session["exercises"]


def _alternatives(api, headers, slot) -> list[int]:
    response = api.get(
        f"/api/v1/exercises/{slot['exercise_id']}/alternatives",
        params={"session_exercise_id": slot["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return [e["id"] for e in response.json()]


def _swap(api, headers, slot_id, exercise_id):
    return api.put(SWAP.format(slot_id), json={"exercise_id": exercise_id}, headers=headers)


def _codes(response) -> list[str]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "invalid_swap"
    assert {d["field"] for d in body["details"]} == {"body.exercise_id"}
    return [d["code"] for d in body["details"]]


def _primary_group(exercise_id: int) -> str:
    return _scalar(
        "SELECT m.group_name FROM exercise_muscle_group g JOIN muscle_group m"
        " ON m.id = g.muscle_group_id WHERE g.exercise_id = :e AND g.is_primary",
        e=exercise_id,
    )


# ---------------------------------------------------------------- edits


def test_patch_changes_the_sent_fields(api):
    headers = _login(api)
    slot, _ = _slot(_plan(api, headers))

    response = api.patch(
        EDIT.format(slot["id"]), json={"planned_weight": 42.5, "planned_reps": 6}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json() == slot | {"planned_weight": 42.5, "planned_reps": 6}


def test_patch_rejects_empty_null_and_out_of_range_values(api):
    headers = _login(api)
    slot, _ = _slot(_plan(api, headers))

    for body in ({}, {"planned_sets": None}, {"planned_weight": 1000}, {"planned_sets": 0}):
        assert api.patch(EDIT.format(slot["id"]), json=body, headers=headers).status_code == 422


# ---------------------------------------------------------------- swap


def test_a_swap_keeps_sets_reps_rest_and_weight_and_swapping_back_clears_the_original(api):
    headers = _login(api)
    slot, _ = _slot(_plan(api, headers))
    api.patch(EDIT.format(slot["id"]), json={"planned_weight": 60}, headers=headers)
    first, second = _alternatives(api, headers, slot)[:2]

    swapped = _swap(api, headers, slot["id"], first)
    again = _swap(api, headers, slot["id"], second)
    back = _swap(api, headers, slot["id"], slot["exercise_id"])

    kept = ("id", "sort_order", "planned_sets", "planned_reps", "rest_seconds")
    for response, exercise_id, original in (
        (swapped, first, slot["exercise_id"]),
        (again, second, slot["exercise_id"]),  # the planned one stays the original
        (back, slot["exercise_id"], None),
    ):
        assert response.status_code == 200, response.text
        body = response.json()
        assert {k: body[k] for k in kept} == {k: slot[k] for k in kept}
        assert (body["exercise_id"], body["original_exercise_id"], body["planned_weight"]) == (
            exercise_id,
            original,
            60.0,
        )


def test_alternatives_match_the_swap_check(api):
    """B-08 Done: with session_exercise_id the alternatives are exactly the exercises
    a swap accepts (every seeded exercise is tried)."""
    headers = _login(api)
    slot, _ = _slot(_plan(api, headers, level="intermediate", equipment="home"))
    alternatives = set(_alternatives(api, headers, slot))
    accepted = set()

    with _sync_engine().connect() as db:
        exercise_ids = db.execute(text("SELECT id FROM exercise ORDER BY id")).scalars().all()
    for exercise_id in exercise_ids:
        response = _swap(api, headers, slot["id"], exercise_id)
        if response.status_code == 200:
            accepted.add(exercise_id)
            _swap(api, headers, slot["id"], slot["exercise_id"])  # back for the next try

    assert accepted == alternatives and accepted


def test_a_swap_rejects_with_the_rule_that_fails(api):
    headers = _login(api)
    slot, session = _slot(_plan(api, headers))
    group = _primary_group(slot["exercise_id"])
    other_group = _scalar(
        "SELECT g.exercise_id FROM exercise_muscle_group g JOIN muscle_group m"
        " ON m.id = g.muscle_group_id WHERE g.is_primary AND m.group_name <> :g"
        " ORDER BY g.exercise_id LIMIT 1",
        g=group,
    )
    in_session = session[1]["exercise_id"]

    assert _codes(_swap(api, headers, slot["id"], 999999)) == ["unknown_exercise"]
    assert _codes(_swap(api, headers, slot["id"], slot["exercise_id"])) == ["same_exercise"]
    assert "other_muscle_group" in _codes(_swap(api, headers, slot["id"], other_group))
    assert "already_in_session" in _codes(_swap(api, headers, slot["id"], in_session))


def test_a_swap_uses_the_plan_snapshot(api):
    headers = _login(api)
    slot, _ = _slot(_plan(api, headers, level="beginner", equipment="none"))
    group = _primary_group(slot["exercise_id"])
    gym_advanced = _scalar(
        "SELECT e.id FROM exercise e JOIN exercise_muscle_group g ON g.exercise_id = e.id"
        " JOIN muscle_group m ON m.id = g.muscle_group_id WHERE g.is_primary"
        " AND m.group_name = :g AND e.difficulty_level = 'advanced' AND e.equipment = 'gym'"
        " ORDER BY e.id LIMIT 1",  # DB-03 fills every level and equipment cell
        g=group,
    )

    assert _codes(_swap(api, headers, slot["id"], gym_advanced)) == [
        "above_level",
        "needs_equipment",
    ]


def test_a_swap_rejects_an_injury_excluded_exercise(api):
    headers = _login(api)
    slot, _ = _slot(_plan(api, headers))
    target = _alternatives(api, headers, slot)[0]
    with _sync_engine().begin() as db:  # rule 2 of 4.3: the target's primary group is injured
        db.execute(
            text(
                "INSERT INTO injury (user_id, injury_type_id, affected_muscle_group_id, severity,"
                " start_date) SELECT 1, (SELECT min(id) FROM injury_type), g.muscle_group_id,"
                " 'mild', current_date FROM exercise_muscle_group g"
                " WHERE g.exercise_id = :e AND g.is_primary"
            ),
            {"e": target},
        )

    assert _codes(_swap(api, headers, slot["id"], target)) == ["excluded_by_injury"]


# ---------------------------------------------------------------- 404 and 409


def test_another_users_session_exercise_is_404(api):
    ann = _login(api)
    slot, _ = _slot(_plan(api, ann))
    bob = _login(api, "bob@example.com")

    assert (
        api.patch(EDIT.format(slot["id"]), json={"planned_reps": 5}, headers=bob).status_code == 404
    )
    assert _swap(api, bob, slot["id"], slot["exercise_id"]).status_code == 404
    assert api.patch(EDIT.format(999999), json={"planned_reps": 5}, headers=ann).status_code == 404


def test_an_archived_plan_cannot_change(api):
    headers = _login(api)
    old = _plan(api, headers)
    api.post(f"/api/v1/training-plans/{old['id']}/accept", headers=headers)
    new = _plan(api, headers, days=2)
    api.post(f"/api/v1/training-plans/{new['id']}/accept", headers=headers)
    slot, _ = _slot(old)
    target = _alternatives(api, headers, slot)[0]

    assert (
        api.patch(EDIT.format(slot["id"]), json={"planned_reps": 5}, headers=headers).status_code
        == 409
    )
    assert _swap(api, headers, slot["id"], target).status_code == 409
    assert (
        api.get(f"/api/v1/training-plans/{old['id']}", headers=headers).json()["status"]
        == "archived"
    )
