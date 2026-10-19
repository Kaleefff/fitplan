from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.health import HealthReport


class FakeHealthChecker:
    def __init__(self, postgres: str = "ok", mongo: str = "ok") -> None:
        self.report = HealthReport(postgres=postgres, mongo=mongo, version="test")

    async def check(self) -> HealthReport:
        return self.report


@pytest.fixture
def health_checker() -> FakeHealthChecker:
    return FakeHealthChecker()


@pytest.fixture
def client(health_checker: FakeHealthChecker) -> Iterator[TestClient]:
    app = create_app(health_checker=health_checker)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
