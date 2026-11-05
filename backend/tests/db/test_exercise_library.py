"""Exercise library and alternatives on PostgreSQL with the reference seed (B-08).

Loads database/seed/ (DB-02, DB-03); skipped without PostgreSQL. The names below are
the seed's chest exercises (primary group chest).
"""

from sqlalchemy import text

from tests.db import test_training_plans as plans
from tests.db.test_training_plans import _generate, _login, _scalar, _sync_engine

# the fixtures of the training plan tests: the seeded database and the app on it
api = plans.api
sessions = plans.sessions
migrated_db = plans.migrated_db
_close_sync_engine = plans._close_sync_engine

PROFILE = {
    "age": 25,
    "sex": "male",
    "current_weight": 80,
    "height": 180,
    "activity_level_pal": 1.55,
    "goal": "muscle_gain",
    "experience_level": "beginner",
    "equipment": "home",
    "target_value": 85,
}

# chest primaries: (name, difficulty_level, equipment, is_compound)
CHEST = [
    ("Machine chest press", "beginner", "gym", True),
    ("Cable fly", "beginner", "gym", False),
    ("Barbell bench press", "intermediate", "gym", True),
    ("Incline barbell bench press", "intermediate", "gym", True),
    ("Weighted dip", "advanced", "gym", True),
    ("Dumbbell bench press", "beginner", "home", True),
    ("Dumbbell fly", "beginner", "home", False),
    ("Incline dumbbell press", "intermediate", "home", True),
    ("Deficit push-up on dumbbells", "advanced", "home", True),
    ("Push-up", "beginner", "none", True),
    ("Decline push-up", "intermediate", "none", True),
    ("Archer push-up", "advanced", "none", True),
]
LEVELS = ["beginner", "intermediate", "advanced"]
TIERS = ["none", "home", "gym"]
# Shoulder strain lists these chest exercises (injury_type_excluded_exercise)
SHOULDER_STRAIN = {
    "Incline barbell bench press",
    "Weighted dip",
    "Deficit push-up on dumbbells",
    "Archer push-up",
}


def _expected(level="advanced", equipment="gym", exclude=()) -> list[str]:
    """4.9 order: compound first, then name."""
    rows = [
        r
        for r in CHEST
        if LEVELS.index(r[1]) <= LEVELS.index(level)
        and TIERS.index(r[2]) <= TIERS.index(equipment)
        and r[0] not in exclude
    ]
    return [r[0] for r in sorted(rows, key=lambda r: (not r[3], r[0].casefold()))]


def _id(name: str) -> int:
    return _scalar("SELECT id FROM exercise WHERE name = :name", name=name)


def _names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [e["name"] for e in response.json()]


# ---------------------------------------------------------------- list and detail


def test_list_is_paginated_by_name(api):
    headers = _login(api)
    total = _scalar("SELECT count(*) FROM exercise")

    first = api.get("/api/v1/exercises?limit=5", headers=headers).json()
    second = api.get("/api/v1/exercises?limit=5&offset=5", headers=headers).json()

    assert (first["total"], first["limit"], first["offset"]) == (total, 5, 0)
    assert (second["total"], second["offset"]) == (total, 5)
    names = [e["name"] for e in first["items"] + second["items"]]
    assert names == sorted(names, key=str.casefold) and len(set(names)) == 10


def test_list_filters_by_name_group_and_level(api):
    headers = _login(api)
    chest = _scalar("SELECT id FROM muscle_group WHERE group_name = 'chest'")

    found = api.get("/api/v1/exercises?q=PUSH-UP&limit=100", headers=headers).json()
    assert found["total"] == len(found["items"]) > 0
    assert all("push-up" in e["name"].lower() for e in found["items"])

    page = api.get(
        f"/api/v1/exercises?muscle_group_id={chest}&difficulty_level=advanced&limit=100",
        headers=headers,
    ).json()
    assert {"Weighted dip", "Deficit push-up on dumbbells", "Archer push-up"} <= {
        e["name"] for e in page["items"]
    }
    for exercise in page["items"]:
        assert exercise["difficulty_level"] == "advanced"
        assert chest in {g["muscle_group_id"] for g in exercise["muscle_groups"]}


def test_detail_has_every_field(api):
    headers = _login(api)

    exercise = api.get(f"/api/v1/exercises/{_id('Push-up')}", headers=headers).json()

    assert exercise["name"] == "Push-up"
    assert (exercise["difficulty_level"], exercise["equipment"]) == ("beginner", "none")
    assert (exercise["is_compound"], exercise["is_bodyweight"]) == (True, True)
    assert exercise["description"] and exercise["instruction"]
    primary, *secondary = exercise["muscle_groups"]  # primary first
    assert (primary["group_name"], primary["is_primary"]) == ("chest", True)
    assert {(g["group_name"], g["is_primary"]) for g in secondary} == {
        ("triceps", False),
        ("shoulders", False),
    }


def test_unknown_exercise_is_404_and_a_token_is_required(api):
    headers = _login(api)

    assert api.get("/api/v1/exercises/999999", headers=headers).status_code == 404
    assert api.get("/api/v1/exercises/999999/alternatives", headers=headers).status_code == 404
    assert api.get("/api/v1/exercises/0", headers=headers).status_code == 422
    assert api.get("/api/v1/exercises").status_code == 401


# ---------------------------------------------------------------- alternatives (4.9)


def test_alternatives_without_a_profile_have_no_level_or_equipment_limit(api):
    headers = _login(api)

    response = api.get(f"/api/v1/exercises/{_id('Push-up')}/alternatives", headers=headers)

    assert _names(response) == _expected(exclude={"Push-up"})


def test_alternatives_use_the_profile(api):
    headers = _login(api)
    assert api.put("/api/v1/users/me/profile", json=PROFILE, headers=headers).status_code == 200

    response = api.get(f"/api/v1/exercises/{_id('Push-up')}/alternatives", headers=headers)

    assert _names(response) == _expected("beginner", "home", exclude={"Push-up"})
    assert _names(response) == ["Dumbbell bench press", "Dumbbell fly"]


def test_alternatives_never_include_an_injury_excluded_exercise(api):
    headers = _login(api)
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "INSERT INTO injury (user_id, injury_type_id, affected_muscle_group_id, severity,"
                " start_date) SELECT 1, t.id, m.id, 'mild', current_date"
                " FROM injury_type t, muscle_group m"
                " WHERE t.type_name = 'Shoulder strain' AND m.group_name = 'shoulders'"
            )
        )

    response = api.get(f"/api/v1/exercises/{_id('Push-up')}/alternatives", headers=headers)

    assert _names(response) == _expected(exclude={"Push-up"} | SHOULDER_STRAIN)

    # an ended injury no longer applies
    with _sync_engine().begin() as db:
        db.execute(text("UPDATE injury SET is_active = false"))
    response = api.get(f"/api/v1/exercises/{_id('Push-up')}/alternatives", headers=headers)
    assert _names(response) == _expected(exclude={"Push-up"})


def _chest_slot(plan) -> tuple[dict, list[dict]]:
    """A session exercise of the plan with chest as its primary group, and its session."""
    chest = {_id(name) for name, *_ in CHEST}
    for session in plan["sessions"]:
        for slot in session["exercises"]:
            if slot["exercise_id"] in chest:
                return slot, session["exercises"]
    raise AssertionError("the plan has no chest exercise")


def test_alternatives_of_a_session_exercise_use_the_plan_snapshot(api):
    headers = _login(api)
    gym = PROFILE | {"experience_level": "advanced", "equipment": "gym"}
    assert api.put("/api/v1/users/me/profile", json=gym, headers=headers).status_code == 200
    plan = _generate(
        api, headers, goal="muscle_gain", days=1, level="intermediate", equipment="home"
    ).json()
    slot, session = _chest_slot(plan)
    in_session = {name for name, *_ in CHEST if _id(name) in {e["exercise_id"] for e in session}}

    response = api.get(
        f"/api/v1/exercises/{slot['exercise_id']}/alternatives",
        params={"session_exercise_id": slot["id"]},
        headers=headers,
    )

    assert _names(response) == _expected("intermediate", "home", exclude=in_session)


def test_alternatives_of_a_foreign_or_mismatched_session_exercise_are_404(api):
    ann = _login(api)
    plan = _generate(api, ann, goal="muscle_gain", days=1, level="intermediate", equipment="gym")
    slot, _ = _chest_slot(plan.json())
    other_exercise = next(_id(name) for name, *_ in CHEST if _id(name) != slot["exercise_id"])
    bob = _login(api, "bob@example.com")

    def alternatives(headers, exercise_id):
        return api.get(
            f"/api/v1/exercises/{exercise_id}/alternatives",
            params={"session_exercise_id": slot["id"]},
            headers=headers,
        )

    assert alternatives(ann, slot["exercise_id"]).status_code == 200
    assert alternatives(bob, slot["exercise_id"]).status_code == 404
    assert alternatives(ann, other_exercise).status_code == 404
