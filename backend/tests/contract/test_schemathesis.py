"""Property-based checks of the implemented operations against docs/api/openapi.yaml (B-28).

Schemathesis generates requests from the contract, not from the app's own schema, so a
response that drifts from the contract fails here even if FastAPI documents it.
"""

import schemathesis

from app.main import create_app
from tests.conftest import FakeHealthChecker
from tests.contract.test_openapi_drift import CONTRACT_PATH

app = create_app(health_checker=FakeHealthChecker())
app.state.health_checker = FakeHealthChecker()

IMPLEMENTED = sorted(
    operation["operationId"]
    for path in app.openapi()["paths"].values()
    for operation in path.values()
)

schema = schemathesis.openapi.from_path(CONTRACT_PATH)
schema.app = app
schema = schema.include(operation_id=IMPLEMENTED)


@schema.parametrize()
def test_implemented_operations_conform_to_contract(case):
    case.call_and_validate()
