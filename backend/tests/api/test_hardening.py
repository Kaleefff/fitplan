"""Request IDs, CORS, security headers and body limits (api-rules.md "Hardening")."""

import io
import json
import logging
import uuid

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import FakeHealthChecker

APP_ORIGIN = "http://localhost:8081"


@pytest.fixture
def hardened_client():
    settings = Settings(cors_origins=[APP_ORIGIN], max_body_bytes=100, max_upload_body_bytes=200)
    app = create_app(settings=settings, health_checker=FakeHealthChecker())
    router = APIRouter()

    @router.post("/_test/echo")
    async def echo(request: Request) -> dict:
        return {"size": len(await request.body())}

    @router.post("/meals/recognitions")
    async def upload(request: Request) -> dict:
        return {"size": len(await request.body())}

    app.include_router(router, prefix="/api/v1")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_every_response_has_a_request_id(client):
    response = client.get("/api/v1/health")
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_a_valid_client_request_id_is_kept(client):
    request_id = str(uuid.uuid4())
    response = client.get("/api/v1/health", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] == request_id


def test_an_invalid_client_request_id_is_replaced(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "not-a-uuid\nforged"})
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_security_headers(client):
    headers = client.get("/api/v1/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "max-age" in headers["Strict-Transport-Security"]
    assert "default-src 'self'" in headers["Content-Security-Policy"]


def test_error_responses_have_security_headers(client):
    assert client.get("/api/v1/nope").headers["X-Content-Type-Options"] == "nosniff"


def test_docs_page_keeps_its_cdn_scripts(client):
    response = client.get("/api/v1/docs")
    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_cors_allows_a_configured_origin(hardened_client):
    response = hardened_client.options(
        "/api/v1/health",
        headers={"Origin": APP_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == APP_ORIGIN


def test_cors_ignores_other_origins(hardened_client):
    response = hardened_client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_no_cross_origin_access_by_default(client):
    response = client.get("/api/v1/health", headers={"Origin": APP_ORIGIN})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_body_at_the_limit_passes(hardened_client):
    response = hardened_client.post("/api/v1/_test/echo", content=b"x" * 100)
    assert response.json() == {"size": 100}


def test_body_over_the_limit_by_content_length_is_413(hardened_client):
    response = hardened_client.post("/api/v1/_test/echo", content=b"x" * 101)
    assert response.status_code == 413
    assert response.json() == {
        "code": "payload_too_large",
        "message": "Request body too large",
        "details": [],
    }


def test_streamed_body_over_the_limit_is_413(hardened_client):
    def chunks():
        yield b"x" * 60
        yield b"x" * 60

    # a generator body is sent chunked, without Content-Length
    response = hardened_client.post("/api/v1/_test/echo", content=chunks())
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_upload_route_has_the_larger_limit(hardened_client):
    assert hardened_client.post("/api/v1/meals/recognitions", content=b"x" * 200).json() == {
        "size": 200
    }
    response = hardened_client.post("/api/v1/meals/recognitions", content=b"x" * 201)
    assert response.status_code == 413


def test_log_lines_carry_the_request_id(client):
    stream = io.StringIO()
    logging.getLogger().handlers[0].stream = stream
    router = APIRouter()

    @router.get("/_test/log")
    async def log() -> dict:
        logging.getLogger("test").warning("inside a request")
        return {}

    client.app.include_router(router, prefix="/api/v1")
    request_id = str(uuid.uuid4())
    client.get("/api/v1/_test/log", headers={"X-Request-ID": request_id})

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert {"logger": "test", "request_id": request_id}.items() <= lines[0].items()


def test_no_empty_server_header(client):
    assert client.get("/api/v1/health").headers.get_list("server") == []
