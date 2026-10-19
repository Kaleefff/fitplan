"""Checks the implemented models against docs/api/openapi.yaml."""

from pathlib import Path

import pytest
import yaml

from app.core.errors import ErrorCode
from app.main import create_app
from tests.conftest import FakeHealthChecker

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.yaml"

# Codes the backend emits that are not in the contract yet (questions.md, B-01).
PENDING_ERROR_CODES = {ErrorCode.METHOD_NOT_ALLOWED.value}


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def served() -> dict:
    return create_app(health_checker=FakeHealthChecker()).openapi()


def _schema(spec: dict, name: str) -> dict:
    return spec["components"]["schemas"][name]


def test_error_codes_match_contract(contract):
    contract_codes = set(_schema(contract, "Error")["properties"]["code"]["enum"])
    backend_codes = {code.value for code in ErrorCode}
    assert backend_codes - PENDING_ERROR_CODES == contract_codes


def test_health_operation_matches_contract(contract, served):
    contract_op = contract["paths"]["/health"]["get"]
    served_op = served["paths"]["/api/v1/health"]["get"]
    assert served_op["operationId"] == contract_op["operationId"]
    assert contract_op["security"] == []


def test_health_schema_matches_contract(contract, served):
    contract_props = _schema(contract, "Health")["properties"]
    served_props = _schema(served, "Health")["properties"]
    assert set(served_props) == set(contract_props)
    for name, prop in contract_props.items():
        if "enum" in prop:
            assert served_props[name]["enum"] == prop["enum"], name
    required = set(_schema(served, "Health")["required"])
    assert set(_schema(contract, "Health")["required"]) <= required
