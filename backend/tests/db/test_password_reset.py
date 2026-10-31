"""Password reset end to end (B-04): PostgreSQL and a real SMTP server.

aiosmtpd stands in for Mailpit (DB-05): the mail goes over SMTP, the test reads the
link from it and resets. Skipped without PostgreSQL.
"""

import functools
import re
import socket
from collections.abc import Iterator
from email import message_from_bytes, policy
from urllib.parse import parse_qs, urlparse

import pytest
from aiosmtpd.controller import Controller
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.body_metrics import SqlBodyMetricsUnitOfWork
from app.db.repositories.password_resets import SqlPasswordResetRepository
from app.db.repositories.profile_data import SqlProfileUnitOfWork
from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import database_url
from app.main import create_app
from app.services.repositories import Repositories
from tests.conftest import FakeHealthChecker, make_settings
from tests.db.test_repositories import TEST_DB, migrated_db  # noqa: F401  (fixture)

EMAIL, OLD, NEW = "ann@example.com", "secret123", "brandnew456"


@functools.cache
def _sync_engine():
    return create_engine(database_url().set(database=TEST_DB))


@pytest.fixture(scope="module", autouse=True)
def _close_sync_engine():
    yield
    if _sync_engine.cache_info().currsize:
        _sync_engine().dispose()
        _sync_engine.cache_clear()


class Inbox:
    def __init__(self) -> None:
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(message_from_bytes(envelope.content, policy=policy.default))
        return "250 Message accepted"


@pytest.fixture
def inbox() -> Iterator[tuple[Inbox, int]]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    handler = Inbox()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    yield handler, port
    controller.stop()


@pytest.fixture
def api(migrated_db, inbox) -> Iterator[TestClient]:  # noqa: F811
    with _sync_engine().begin() as db:
        db.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
    engine = create_async_engine(database_url().set(database=TEST_DB))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repositories = Repositories(
        users=SqlUserRepository(factory),
        refresh_tokens=SqlRefreshTokenRepository(factory),
        profiles=SqlProfileReader(factory),
        workouts=SqlWorkoutUnitOfWork(factory),
        training_plans=SqlTrainingPlanUnitOfWork(factory),
        profile_data=SqlProfileUnitOfWork(factory),
        password_resets=SqlPasswordResetRepository(factory),
        body_metrics=SqlBodyMetricsUnitOfWork(factory),
    )
    settings = make_settings(smtp_host="127.0.0.1", smtp_port=inbox[1])
    app = create_app(
        settings=settings, health_checker=FakeHealthChecker(), repositories=repositories
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
        client.portal.call(engine.dispose)


def _post(api, path, body):
    return api.post(f"/api/v1/auth/{path}", json=body)


def _token(message) -> str:
    link = re.search(r"fitplan://reset-password\?\S+", message.get_content()).group(0)
    return parse_qs(urlparse(link).query)["token"][0]


def test_mailed_link_resets_the_password_once_and_ends_every_session(api, inbox):
    messages = inbox[0].messages
    session = _post(
        api, "register", {"email": EMAIL, "password": OLD, "name": "Ann", "surname": "N"}
    )
    refresh = session.json()["refresh_token"]

    assert _post(api, "password/forgot", {"email": EMAIL}).status_code == 202

    assert len(messages) == 1
    mail = messages[0]
    assert (mail["To"], mail["Subject"]) == (EMAIL, "Reset your FitPlan Pro password")
    token = _token(mail)

    weak = _post(api, "password/reset", {"token": token, "new_password": "short"})
    assert weak.status_code == 422  # the token is not spent by a rejected password
    assert _post(api, "password/reset", {"token": token, "new_password": NEW}).status_code == 204

    assert _post(api, "refresh", {"refresh_token": refresh}).status_code == 401
    assert _post(api, "login", {"email": EMAIL, "password": OLD}).status_code == 401
    assert _post(api, "login", {"email": EMAIL, "password": NEW}).status_code == 200

    reused = _post(api, "password/reset", {"token": token, "new_password": "another789"})
    assert reused.status_code == 422
    assert reused.json()["details"][0]["code"] == "invalid_token"


def test_unknown_email_gets_the_same_answer_and_no_mail(api, inbox):
    messages = inbox[0].messages
    _post(api, "register", {"email": EMAIL, "password": OLD, "name": "Ann", "surname": "N"})

    known = _post(api, "password/forgot", {"email": EMAIL})
    unknown = _post(api, "password/forgot", {"email": "nobody@example.com"})

    assert (known.status_code, known.content) == (unknown.status_code, unknown.content)
    assert len(messages) == 1


def test_expired_token_is_rejected(api, inbox):
    messages = inbox[0].messages
    _post(api, "register", {"email": EMAIL, "password": OLD, "name": "Ann", "surname": "N"})
    _post(api, "password/forgot", {"email": EMAIL})
    with _sync_engine().begin() as db:
        db.execute(
            text(
                "UPDATE password_reset_token SET created_at = now() - interval '2 hours',"
                " expires_at = now() - interval '1 hour'"
            )
        )

    response = _post(api, "password/reset", {"token": _token(messages[0]), "new_password": NEW})

    assert response.status_code == 422
    assert _post(api, "login", {"email": EMAIL, "password": OLD}).status_code == 200


def test_a_newer_reset_ends_older_links(api, inbox):
    messages = inbox[0].messages
    _post(api, "register", {"email": EMAIL, "password": OLD, "name": "Ann", "surname": "N"})
    _post(api, "password/forgot", {"email": EMAIL})
    _post(api, "password/forgot", {"email": EMAIL})
    first, second = (_token(m) for m in messages)

    assert _post(api, "password/reset", {"token": second, "new_password": NEW}).status_code == 204
    assert _post(api, "password/reset", {"token": first, "new_password": "x9" * 5}).status_code == (
        422
    )


def test_stored_tokens_are_hashes(api, inbox):
    messages = inbox[0].messages
    _post(api, "register", {"email": EMAIL, "password": OLD, "name": "Ann", "surname": "N"})
    _post(api, "password/forgot", {"email": EMAIL})
    with _sync_engine().connect() as db:
        stored = db.execute(text("SELECT token_hash FROM password_reset_token")).scalar_one()
    assert _token(messages[0]) not in stored
    assert len(stored) == 64


def test_forgot_is_rate_limited(api):
    for _ in range(10):
        _post(api, "password/forgot", {"email": "x@example.com"})
    assert _post(api, "password/forgot", {"email": "x@example.com"}).status_code == 429
