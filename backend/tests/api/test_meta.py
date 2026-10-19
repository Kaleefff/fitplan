from fastapi import APIRouter, Query

from app.core.errors import AppError, ErrorCode
from app.services.health import HealthReport


def test_health_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "ok", "mongo": "ok", "version": "test"}


def test_health_degraded_when_a_store_is_down(client, health_checker):
    health_checker.report = HealthReport(postgres="ok", mongo="down", version="test")
    body = client.get("/api/v1/health").json()
    assert body["status"] == "degraded"
    assert body["mongo"] == "down"


def test_unknown_route_uses_error_model(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Not Found", "details": []}


def test_wrong_method_uses_error_model(client):
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


def _add_test_routes(client):
    router = APIRouter()

    @router.get("/_test/validate")
    async def validate(age: int = Query(ge=16, le=100)) -> dict:
        return {"age": age}

    @router.get("/_test/app-error")
    async def app_error() -> dict:
        raise AppError(409, ErrorCode.CONFLICT, "Already exists", [{"field": "body.email"}])

    @router.get("/_test/crash")
    async def crash() -> dict:
        raise RuntimeError("secret detail")

    client.app.include_router(router, prefix="/api/v1")


def test_validation_error_is_422_with_field_details(client):
    _add_test_routes(client)
    response = client.get("/api/v1/_test/validate", params={"age": 15})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "query.age"
    assert body["details"][0]["code"] == "greater_than_equal"


def test_app_error_keeps_code_and_details(client):
    _add_test_routes(client)
    response = client.get("/api/v1/_test/app-error")
    assert response.status_code == 409
    assert response.json() == {
        "code": "conflict",
        "message": "Already exists",
        "details": [{"field": "body.email"}],
    }


def test_unhandled_error_hides_internals(client):
    _add_test_routes(client)
    response = client.get("/api/v1/_test/crash")
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Internal server error",
        "details": [],
    }


def test_openapi_is_served_under_prefix(client):
    spec = client.get("/api/v1/openapi.json").json()
    assert spec["paths"]["/api/v1/health"]["get"]["operationId"] == "getHealth"
