from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, auth_rate_limit, get_current_user, owned_or_404
from app.core.errors import AppError
from app.core.security import create_access_token
from tests.conftest import TEST_JWT_SECRET


def _token(user_id: int, issued: datetime | None = None) -> str:
    issued = issued or datetime.now(UTC)
    return create_access_token(user_id, TEST_JWT_SECRET, timedelta(minutes=15), issued)


@pytest.fixture
def api(client):
    router = APIRouter()

    @router.get("/_test/me")
    async def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
        return {"id": user.id}

    @router.post("/_test/login", dependencies=[Depends(auth_rate_limit)])
    async def login() -> dict:
        return {}

    @router.post("/_test/register", dependencies=[Depends(auth_rate_limit)])
    async def register() -> dict:
        return {}

    client.app.include_router(router, prefix="/api/v1")
    return client


def test_valid_token_gives_the_user(api):
    response = api.get("/api/v1/_test/me", headers={"Authorization": f"Bearer {_token(7)}"})
    assert response.status_code == 200
    assert response.json() == {"id": 7}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer garbage"},
        {"Authorization": f"Basic {_token(7)}"},
        {"Authorization": f"Bearer {_token(7, datetime.now(UTC) - timedelta(minutes=16))}"},
    ],
    ids=["missing", "garbage", "wrong-scheme", "expired"],
)
def test_bad_token_is_401_with_the_error_model(api, headers):
    response = api.get("/api/v1/_test/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.json()["details"] == []


def test_auth_routes_are_limited_per_route(api):
    for _ in range(10):
        assert api.post("/api/v1/_test/login").status_code == 200

    limited = api.post("/api/v1/_test/login")

    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    assert api.post("/api/v1/_test/register").status_code == 200


@dataclass
class Row:
    id: int
    user_id: int


def test_owned_row_is_returned():
    row = Row(id=1, user_id=7)
    assert owned_or_404(row, CurrentUser(id=7)) is row


@pytest.mark.parametrize("row", [None, Row(id=1, user_id=8)], ids=["missing", "foreign"])
def test_missing_and_foreign_rows_look_the_same(row):
    with pytest.raises(AppError) as error:
        owned_or_404(row, CurrentUser(id=7))
    assert (error.value.status_code, error.value.code) == (404, "not_found")
