"""Property-based checks of the implemented operations against docs/api/openapi.yaml (B-28).

Schemathesis generates requests from the contract, not from the app's own schema, so a
response that drifts from the contract fails here even if FastAPI documents it.
"""

import schemathesis
from schemathesis.specs.openapi.checks import positive_data_acceptance

from app.main import create_app
from tests.conftest import FakeHealthChecker, make_settings
from tests.contract.test_openapi_drift import CONTRACT_PATH
from tests.fakes import fake_repositories

# test settings (JWT secret) and fakes, so authenticated operations answer like in production
app = create_app(
    settings=make_settings(),
    health_checker=FakeHealthChecker(),
    repositories=fake_repositories(),
)
app.state.health_checker = FakeHealthChecker()

IMPLEMENTED = sorted(
    operation["operationId"]
    for path in app.openapi()["paths"].values()
    for operation in path.values()
)

schema = schemathesis.openapi.from_path(CONTRACT_PATH)
schema.app = app
schema = schema.include(operation_id=IMPLEMENTED)


# A new password must be 8-72 *bytes* (bcrypt); JSON Schema counts characters, so
# 72 Polish letters are schema-valid and still rejected. Everything else about these
# operations is checked as usual.
NEW_PASSWORD_OPERATIONS = {"register", "resetPassword", "changePassword"}


@schema.parametrize()
def test_implemented_operations_conform_to_contract(case):
    if case.operation.definition.raw.get("operationId") in NEW_PASSWORD_OPERATIONS:
        case.call_and_validate(excluded_checks=[positive_data_acceptance])
    else:
        case.call_and_validate()
