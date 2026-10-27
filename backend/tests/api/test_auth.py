"""Register, login, refresh, logout (B-03) on in-memory repositories."""

import pytest
from fastapi.testclient import TestClient

from app.core.security import decode_access_token
from app.main import create_app
from tests.conftest import TEST_JWT_SECRET, FakeHealthChecker, make_settings
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


def _register(api, email="ann@example.com", password=PASSWORD, name="Ann", surname="Nowak"):
    return api.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": name, "surname": surname},
    )


def _login(api, email="ann@example.com", password=PASSWORD):
    return api.post("/api/v1/auth/login", json={"email": email, "password": password})


def _bearer(pair: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {pair['access_token']}"}


# ---------------------------------------------------------------- register


def test_register_signs_the_user_in(api, repos):
    response = _register(api)

    assert response.status_code == 201
    pair = response.json()
    assert set(pair) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert (pair["token_type"], pair["expires_in"]) == ("bearer", 900)
    user = repos.users.rows[decode_access_token(pair["access_token"], TEST_JWT_SECRET)]
    assert user.email == "ann@example.com"
    assert user.password_hash.startswith("$2b$")
    assert PASSWORD not in response.text


def test_names_are_trimmed(api, repos):
    _register(api, name="  Ann ", surname=" Nowak  ")
    assert (repos.users.rows[1].name, repos.users.rows[1].surname) == ("Ann", "Nowak")


def test_duplicate_email_is_409_on_the_email_field(api):
    _register(api)
    response = _register(api)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["details"][0]["field"] == "body.email"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"password": "onlyletters"}, "body.password"),
        ({"password": "12345678"}, "body.password"),
        ({"password": "a1"}, "body.password"),
        ({"password": "a1" * 37}, "body.password"),  # 74 bytes
        ({"email": "not-an-email"}, "body.email"),
        ({"email": "a" * 90 + "@example.com"}, "body.email"),
        ({"name": "   "}, "body.name"),
        ({"surname": "x" * 101}, "body.surname"),
    ],
)
def test_invalid_registration_is_422_on_the_field(api, overrides, field):
    response = _register(api, **overrides)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert [detail["field"] for detail in body["details"]] == [field]


def test_undecodable_body_is_422(api):
    response = api.post(
        "/api/v1/auth/register",
        content=b"\xff\xfe",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ---------------------------------------------------------------- login


def test_login(api):
    _register(api)
    response = _login(api)

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"], TEST_JWT_SECRET) == 1


def test_wrong_password_and_unknown_email_answer_the_same(api):
    _register(api)
    wrong_password = _login(api, password="wrong1234")
    unknown_email = _login(api, email="bob@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["code"] == "invalid_credentials"


def test_social_only_account_cannot_log_in_with_a_password(api, repos):
    import asyncio

    asyncio.run(
        repos.users.add(email="ann@example.com", password_hash=None, name="Ann", surname="N")
    )
    assert _login(api).json()["code"] == "invalid_credentials"


def test_register_and_login_are_rate_limited(api):
    for _ in range(10):
        _login(api, email="bob@example.com")
    response = _login(api, email="bob@example.com")

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


# ---------------------------------------------------------------- refresh and logout


def test_refresh_rotates_and_reuse_revokes_the_family(api):
    first = _register(api).json()

    second = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]

    reuse = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401
    assert reuse.json()["code"] == "unauthorized"
    after_reuse = api.post(
        "/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
    )
    assert after_reuse.status_code == 401


def test_logout_revokes_the_family(api):
    pair = _register(api).json()

    response = api.post(
        "/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}, headers=_bearer(pair)
    )

    assert response.status_code == 204
    assert response.content == b""
    refresh = api.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert refresh.status_code == 401


def test_logout_needs_an_access_token(api):
    pair = _register(api).json()
    response = api.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 401


def test_logout_with_another_users_refresh_token_is_401_and_revokes_nothing(api):
    ann = _register(api).json()
    bob = _register(api, email="bob@example.com").json()

    response = api.post(
        "/api/v1/auth/logout", json={"refresh_token": bob["refresh_token"]}, headers=_bearer(ann)
    )

    assert response.status_code == 401
    still_valid = api.post("/api/v1/auth/refresh", json={"refresh_token": bob["refresh_token"]})
    assert still_valid.status_code == 200
