"""Custom exercise endpoints on PostgreSQL (B-29; FR-P10, FR-A1, D26).

The repository rules are DB-16's and tested in test_custom_exercises.py; these tests
check the HTTP layer: status codes, error fields, `is_custom`, "My exercises", the 404
for another user's exercise on every read and write, and swaps into own exercises.
Uses the fixtures of the training plan tests; skipped without PostgreSQL.
"""

from tests.db import test_training_plans as plans
from tests.db.test_training_plans import _generate, _login, _scalar

api = plans.api
sessions = plans.sessions
migrated_db = plans.migrated_db
_close_sync_engine = plans._close_sync_engine

EXERCISES = "/api/v1/exercises"


def _group(name: str) -> int:
    return _scalar("SELECT id FROM muscle_group WHERE group_name = :n", n=name)


def _body(**changes) -> dict:
    return {
        "name": "Towel row",
        "difficulty_level": "beginner",
        "equipment": "none",
        "primary_muscle_group_id": _group("back"),
        "secondary_muscle_group_ids": [_group("biceps")],
    } | changes


def _create(api, headers, **changes) -> dict:
    response = api.post(EXERCISES, json=_body(**changes), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _details(response, status: int) -> list[tuple[str | None, str]]:
    assert response.status_code == status, response.text
    return [(d.get("field"), d["code"]) for d in response.json()["details"]]


def _names(api, headers, **params) -> list[str]:
    response = api.get(EXERCISES, params={"limit": 100, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return [e["name"] for e in response.json()["items"]]


# ---------------------------------------------------------------- create and read


def test_create_returns_the_exercise_marked_custom_with_defaults(api):
    headers = _login(api)

    created = _create(api, headers, name="  Towel row  ")

    assert {k: created[k] for k in ("name", "is_custom", "is_compound", "description")} == {
        "name": "Towel row",
        "is_custom": True,
        "is_compound": False,
        "description": "",
    }
    assert [(g["group_name"], g["is_primary"]) for g in created["muscle_groups"]] == [
        ("back", True),
        ("biceps", False),
    ]
    assert api.get(f"{EXERCISES}/{created['id']}", headers=headers).json() == created


def test_my_exercises_and_the_library_list(api):
    headers = _login(api)
    _create(api, headers)

    assert _names(api, headers, custom_only=True) == ["Towel row"]
    assert "Towel row" in _names(api, headers, q="row")
    library = api.get(EXERCISES, params={"limit": 1}, headers=headers).json()["items"][0]
    assert library["is_custom"] is False


def test_another_user_never_sees_or_changes_it(api):
    ann = _login(api)
    exercise = _create(api, ann)
    bob = _login(api, "bob@example.com")
    url = f"{EXERCISES}/{exercise['id']}"

    assert "Towel row" not in _names(api, bob, q="Towel")
    assert _names(api, bob, custom_only=True) == []
    assert api.get(url, headers=bob).status_code == 404
    assert api.get(f"{url}/alternatives", headers=bob).status_code == 404
    assert api.patch(url, json={"name": "Mine"}, headers=bob).status_code == 404
    assert api.delete(url, headers=bob).status_code == 404
    assert api.get(url, headers=ann).status_code == 200


# ---------------------------------------------------------------- validation


def test_invalid_bodies_are_422_with_the_field(api):
    headers = _login(api)
    back = _group("back")

    cases = [
        ({"name": "   "}, ("body.name", None)),
        ({"secondary_muscle_group_ids": [back]}, ("body.secondary_muscle_group_ids", None)),
        ({"primary_muscle_group_id": 9999}, ("body.primary_muscle_group_id", "not_found")),
        (
            {"secondary_muscle_group_ids": [_group("biceps"), 9999]},
            ("body.secondary_muscle_group_ids.1", "not_found"),
        ),
    ]
    for changes, (field, code) in cases:
        details = _details(api.post(EXERCISES, json=_body(**changes), headers=headers), 422)
        assert field in [f for f, _ in details], (changes, details)
        if code:
            assert (field, code) in details
    missing_level = {k: v for k, v in _body().items() if k != "difficulty_level"}
    assert api.post(EXERCISES, json=missing_level, headers=headers).status_code == 422


def test_names_are_unique_per_user_in_any_case_but_may_equal_a_library_name(api):
    headers = _login(api)
    _create(api, headers)
    library_name = _scalar("SELECT name FROM exercise WHERE user_id IS NULL ORDER BY id LIMIT 1")

    taken = api.post(EXERCISES, json=_body(name="TOWEL ROW"), headers=headers)

    assert _details(taken, 409) == [("body.name", "duplicate")]
    assert _create(api, headers, name=library_name)["name"] == library_name
    assert _create(api, _login(api, "bob@example.com"))["name"] == "Towel row"


# ---------------------------------------------------------------- edit


def test_patch_changes_sent_fields_and_one_group_field_keeps_the_other(api):
    headers = _login(api)
    exercise = _create(api, headers)
    url = f"{EXERCISES}/{exercise['id']}"

    renamed = api.patch(url, json={"name": "Door row", "equipment": "home"}, headers=headers)
    regrouped = api.patch(
        url, json={"secondary_muscle_group_ids": [_group("shoulders")]}, headers=headers
    )

    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["equipment"]) == ("Door row", "home")
    assert regrouped.status_code == 200, regrouped.text
    assert [(g["group_name"], g["is_primary"]) for g in regrouped.json()["muscle_groups"]] == [
        ("back", True),
        ("shoulders", False),
    ]
    # the new primary is a kept secondary: 422, nothing changes
    clash = api.patch(url, json={"primary_muscle_group_id": _group("shoulders")}, headers=headers)
    assert _details(clash, 422) == [("body.secondary_muscle_group_ids", "invalid_value")]


def test_patch_rejects_empty_and_null_and_library_exercises_are_read_only(api):
    headers = _login(api)
    url = f"{EXERCISES}/{_create(api, headers)['id']}"
    library_id = _scalar("SELECT id FROM exercise WHERE user_id IS NULL ORDER BY id LIMIT 1")

    assert api.patch(url, json={}, headers=headers).status_code == 422
    assert api.patch(url, json={"name": None}, headers=headers).status_code == 422
    library_url = f"{EXERCISES}/{library_id}"
    assert api.patch(library_url, json={"name": "Mine"}, headers=headers).status_code == 404
    assert api.delete(library_url, headers=headers).status_code == 404


# ---------------------------------------------------------------- swap and delete


def test_an_own_exercise_can_replace_a_planned_one_and_is_then_in_use(api):
    headers = _login(api)
    plan = _generate(api, headers).json()
    slot = plan["sessions"][0]["exercises"][0]
    primary = _scalar(
        "SELECT muscle_group_id FROM exercise_muscle_group WHERE exercise_id = :e AND is_primary",
        e=slot["exercise_id"],
    )
    own = _create(api, headers, primary_muscle_group_id=primary, secondary_muscle_group_ids=[])
    alternatives = api.get(
        f"{EXERCISES}/{slot['exercise_id']}/alternatives",
        params={"session_exercise_id": slot["id"]},
        headers=headers,
    ).json()
    bob = _login(api, "bob@example.com")
    bob_slot = _generate(api, bob).json()["sessions"][0]["exercises"][0]

    assert own["id"] in [e["id"] for e in alternatives]
    swapped = api.put(
        f"/api/v1/session-exercises/{slot['id']}/swap",
        json={"exercise_id": own["id"]},
        headers=headers,
    )
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["exercise_id"] == own["id"]
    # another user's custom exercise is unknown to the swap
    stolen = api.put(
        f"/api/v1/session-exercises/{bob_slot['id']}/swap",
        json={"exercise_id": own["id"]},
        headers=bob,
    )
    assert _details(stolen, 422) == [("body.exercise_id", "unknown_exercise")]
    # still planned: 409 in_use, and it stays
    url = f"{EXERCISES}/{own['id']}"
    assert _details(api.delete(url, headers=headers), 409) == [(None, "in_use")]
    assert api.get(url, headers=headers).status_code == 200


def test_an_unused_exercise_is_deleted_for_real(api):
    headers = _login(api)
    url = f"{EXERCISES}/{_create(api, headers)['id']}"

    assert api.delete(url, headers=headers).status_code == 204
    assert api.get(url, headers=headers).status_code == 404
    assert api.delete(url, headers=headers).status_code == 404
    assert _scalar("SELECT count(*) FROM exercise WHERE user_id IS NOT NULL") == 0
