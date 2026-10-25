"""GET /nutrition/targets (B-10): the vectors of algorithms.md section 2 end to end."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.domain.constants import Goal, Sex
from app.main import create_app
from app.services.nutrition import ProfileRecord
from tests.conftest import TEST_JWT_SECRET, FakeHealthChecker, make_settings
from tests.domain.test_nutrition import VECTORS
from tests.fakes import InMemoryProfileReader

URL = "/api/v1/nutrition/targets"


def _auth(user_id: int) -> dict[str, str]:
    token = create_access_token(user_id, TEST_JWT_SECRET, timedelta(minutes=15), datetime.now(UTC))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def profiles() -> InMemoryProfileReader:
    return InMemoryProfileReader()


@pytest.fixture
def api(profiles):
    app = create_app(
        settings=make_settings(), health_checker=FakeHealthChecker(), profile_reader=profiles
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize(
    ("sex", "kg", "cm", "age", "pal", "goal", "bmr", "tdee", "target", "protein", "fat", "carbs"),
    VECTORS,
)
def test_targets_match_algorithms_vectors(
    api, profiles, sex, kg, cm, age, pal, goal, bmr, tdee, target, protein, fat, carbs
):
    profiles.profiles[1] = ProfileRecord(age, sex, D(kg), int(cm), D(pal), goal)

    response = api.get(URL, headers=_auth(1))

    assert response.status_code == 200
    assert response.json() == {
        "goal": goal.value,
        "bmr": float(bmr),
        "tdee": tdee,
        "target_kcal": target,
        "protein_g": float(protein),
        "fat_g": float(fat),
        "carbs_g": float(carbs),
    }


def test_numbers_are_json_numbers(api, profiles):
    profiles.profiles[1] = ProfileRecord(30, Sex.FEMALE, D("60"), 165, D("1.375"), Goal.MAINTENANCE)
    body = api.get(URL, headers=_auth(1)).json()
    assert all(isinstance(body[key], int | float) for key in body if key != "goal")


def test_without_a_profile_is_404(api):
    response = api.get(URL, headers=_auth(1))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_another_users_profile_is_never_used(api, profiles):
    profiles.profiles[2] = ProfileRecord(25, Sex.MALE, D("80"), 180, D("1.55"), Goal.STRENGTH)
    assert api.get(URL, headers=_auth(1)).status_code == 404


def test_without_a_token_is_401(api):
    response = api.get(URL)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
