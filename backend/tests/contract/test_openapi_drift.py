"""The generated OpenAPI must match docs/api/openapi.yaml (B-28)."""

import copy
from pathlib import Path

import pytest
import yaml
from fastapi import APIRouter, Query

from app.core.errors import VALIDATION_ERROR_RESPONSE, ErrorCode
from app.main import create_app
from tests.conftest import FakeHealthChecker
from tests.contract.drift import HTTP_METHODS, compare_specs
from tests.contract.pending import PENDING_OPERATIONS

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.yaml"


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def served() -> dict:
    return create_app(health_checker=FakeHealthChecker()).openapi()


def test_generated_openapi_matches_contract(served, contract):
    assert compare_specs(served, contract) == []


def _operation_ids(spec: dict) -> set[str]:
    return {
        operation["operationId"]
        for item in spec["paths"].values()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def test_pending_list_equals_the_missing_operations(served, contract):
    assert len(PENDING_OPERATIONS) == len(set(PENDING_OPERATIONS)), "duplicate in pending.py"
    missing = _operation_ids(contract) - _operation_ids(served)
    assert set(PENDING_OPERATIONS) == missing


def test_error_codes_match_contract(contract):
    contract_codes = set(contract["components"]["schemas"]["Error"]["properties"]["code"]["enum"])
    assert {code.value for code in ErrorCode} == contract_codes


def test_drift_in_a_response_schema_is_reported(served, contract):
    changed = copy.deepcopy(served)
    health = changed["components"]["schemas"]["Health"]["properties"]
    health["uptime"] = {"type": "integer"}
    health["status"]["enum"].append("starting")
    del health["version"]

    problems = compare_specs(changed, contract)

    assert "GET /health 200.uptime: not in the contract" in problems
    assert "GET /health 200.version: missing in the app" in problems
    assert any(problem.startswith("GET /health 200.status: enum") for problem in problems)


def test_undeclared_operation_is_reported(contract):
    app = create_app(health_checker=FakeHealthChecker())
    router = APIRouter()

    @router.get("/health/extra", operation_id="extra")
    async def extra() -> dict:
        return {}

    app.include_router(router, prefix="/api/v1")

    assert compare_specs(app.openapi(), contract) == [
        "GET /health/extra: operation not in the contract"
    ]


def _problems_of_list_exercises(router: APIRouter, contract: dict) -> list[str]:
    """Serves the contract operation GET /exercises with a query parameter."""
    app = create_app(health_checker=FakeHealthChecker())

    @router.get("/exercises", operation_id="listExercises")
    async def list_exercises(limit: int = Query(20)) -> dict:
        return {}

    app.include_router(router, prefix="/api/v1")
    return compare_specs(app.openapi(), contract)


def test_validation_error_response_uses_the_contract_model(contract):
    with_default = _problems_of_list_exercises(APIRouter(), contract)
    with_contract_model = _problems_of_list_exercises(
        APIRouter(responses=VALIDATION_ERROR_RESPONSE), contract
    )

    assert any(problem.startswith("GET /exercises 422") for problem in with_default)
    assert not any(problem.startswith("GET /exercises 422") for problem in with_contract_model)
