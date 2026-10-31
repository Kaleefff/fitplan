"""Account settings (B-05) on in-memory repositories; deletion on PostgreSQL is in
tests/db/test_account_deletion.py."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FakeHealthChecker, make_settings
from tests.fakes import fake_repositories

PASSWORD = "secret123"


@pytest.fixture
def repos():
    return fake_repositories()


@pytest.fixture
def api(repos):
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), repositories=repos
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _register(api, email="ann@example.com") -> dict:
    return api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Ann", "surname": "Nowak"},
    ).json()


def _auth(pair: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {pair['access_token']}"}


def test_get_me(api):
    pair = _register(api)
    me = api.get("/api/v1/users/me", headers=_auth(pair))

    assert me.status_code == 200
    assert {k: me.json()[k] for k in ("id", "email", "name", "surname", "timezone")} == {
        "id": 1,
        "email": "ann@example.com",
        "name": "Ann",
        "surname": "Nowak",
        "timezone": "Europe/Warsaw",
    }
    assert "password" not in me.text and "password_hash" not in me.json()


def test_patch_me(api):
    headers = _auth(_register(api))
    patched = api.patch(
        "/api/v1/users/me",
        json={"name": "  Anna ", "timezone": "America/New_York"},
        headers=headers,
    )

    assert patched.status_code == 200
    assert (patched.json()["name"], patched.json()["timezone"]) == ("Anna", "America/New_York")
    assert patched.json()["surname"] == "Nowak"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"timezone": "Mars/Olympus"}, "body.timezone"),
        ({"name": ""}, "body.name"),
        ({}, "body"),
    ],
)
def test_patch_me_validation(api, body, field):
    headers = _auth(_register(api))
    response = api.patch("/api/v1/users/me", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["details"][0]["field"] == field


# ---------------------------------------------------------------- email


def test_change_email_keeps_sessions(api):
    pair = _register(api)
    changed = api.post(
        "/api/v1/users/me/email",
        json={"new_email": "anna@example.com", "current_password": PASSWORD},
        headers=_auth(pair),
    )

    assert changed.status_code == 200
    assert changed.json()["email"] == "anna@example.com"
    refreshed = api.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert refreshed.status_code == 200
    login = {"email": "anna@example.com", "password": PASSWORD}
    assert api.post("/api/v1/auth/login", json=login).status_code == 200


def test_change_email_cases(api, repos):
    headers = _auth(_register(api))
    _register(api, "bob@example.com")

    def change(email, password=PASSWORD):
        return api.post(
            "/api/v1/users/me/email",
            json={"new_email": email, "current_password": password},
            headers=headers,
        )

    assert change("x@example.com", "wrong1234").json()["code"] == "invalid_credentials"
    taken = change("bob@example.com")
    assert taken.status_code == 409
    assert taken.json()["details"][0]["field"] == "body.new_email"
    assert change("ann@example.com").status_code == 200  # the same email: no-op
    assert repos.users.rows[1].email == "ann@example.com"


def test_social_only_account_has_no_password_to_check(api, repos):
    headers = _auth(_register(api))
    asyncio.run(repos.users.set_password(1, None))

    response = api.post(
        "/api/v1/users/me/email",
        json={"new_email": "x@example.com", "current_password": "anything1"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["details"][0]["code"] == "no_password"
    change = api.post(
        "/api/v1/users/me/password",
        json={"current_password": "anything1", "new_password": "newpass123"},
        headers=headers,
    )
    assert change.json()["details"][0]["code"] == "no_password"


# ---------------------------------------------------------------- password


def test_change_password_ends_every_session(api, repos):
    pair = _register(api)
    other_device = api.post(
        "/api/v1/auth/login", json={"email": "ann@example.com", "password": PASSWORD}
    ).json()

    changed = api.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "newpass123"},
        headers=_auth(pair),
    )

    assert changed.status_code == 204
    for tokens in (pair, other_device):
        refresh = api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refresh.status_code == 401
    old = {"email": "ann@example.com", "password": PASSWORD}
    new = {"email": "ann@example.com", "password": "newpass123"}
    assert api.post("/api/v1/auth/login", json=old).status_code == 401
    assert api.post("/api/v1/auth/login", json=new).status_code == 200


def test_change_password_needs_the_current_one_and_the_policy(api):
    headers = _auth(_register(api))
    wrong = api.post(
        "/api/v1/users/me/password",
        json={"current_password": "wrong1234", "new_password": "newpass123"},
        headers=headers,
    )
    weak = api.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=headers,
    )
    assert (wrong.status_code, wrong.json()["code"]) == (401, "invalid_credentials")
    assert weak.status_code == 422


def test_password_checking_routes_are_rate_limited(api):
    headers = _auth(_register(api))
    for _ in range(10):
        api.post(
            "/api/v1/users/me/password",
            json={"current_password": "wrong1234", "new_password": "newpass123"},
            headers=headers,
        )
    limited = api.post(
        "/api/v1/users/me/password",
        json={"current_password": PASSWORD, "new_password": "newpass123"},
        headers=headers,
    )
    assert limited.status_code == 429


# ---------------------------------------------------------------- delete


def test_delete_needs_the_password(api, repos):
    pair = _register(api)
    headers = _auth(pair)

    missing = api.post("/api/v1/users/me/delete", json={}, headers=headers)
    wrong = api.post("/api/v1/users/me/delete", json={"password": "wrong1234"}, headers=headers)
    assert missing.status_code == wrong.status_code == 401
    assert 1 in repos.users.rows

    deleted = api.post("/api/v1/users/me/delete", json={"password": PASSWORD}, headers=headers)
    assert deleted.status_code == 204
    assert repos.users.rows == {}
    # the access token is still valid for minutes, but the account is gone
    assert api.get("/api/v1/users/me", headers=headers).status_code == 401


def test_social_only_account_deletes_without_a_password(api, repos):
    headers = _auth(_register(api))
    asyncio.run(repos.users.set_password(1, None))

    assert api.post("/api/v1/users/me/delete", json={}, headers=headers).status_code == 204


def test_null_is_rejected_on_its_own_field(api):
    headers = _auth(_register(api))
    response = api.patch("/api/v1/users/me", json={"surname": None}, headers=headers)
    assert response.status_code == 422
    assert [d["field"] for d in response.json()["details"]] == ["body.surname"]
