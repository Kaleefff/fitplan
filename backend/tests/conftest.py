from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.health import HealthReport
from tests.fakes import fake_repositories

TEST_JWT_SECRET = "test-secret-with-at-least-32-bytes!"


def make_settings(**overrides: object) -> Settings:
    """Settings without the repository .env, with a test JWT secret and fast bcrypt."""
    values = {"jwt_secret": TEST_JWT_SECRET, "bcrypt_rounds": 4, **overrides}
    return Settings(_env_file=None, **values)


class FakeHealthChecker:
    def __init__(self, postgres: str = "ok", mongo: str = "ok") -> None:
        self.report = HealthReport(postgres=postgres, mongo=mongo, version="test")

    async def check(self) -> HealthReport:
        return self.report


@pytest.fixture
def health_checker() -> FakeHealthChecker:
    return FakeHealthChecker()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(health_checker: FakeHealthChecker, settings: Settings) -> Iterator[TestClient]:
    app = create_app(
        settings=settings, health_checker=health_checker, repositories=fake_repositories()
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
