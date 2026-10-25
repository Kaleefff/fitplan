import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import decode_access_token, hash_opaque_token
from app.services.tokens import InvalidRefreshTokenError, TokenService
from tests.conftest import TEST_JWT_SECRET, make_settings
from tests.fakes import InMemoryRefreshTokenRepository

USER, OTHER_USER = 1, 2


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def repo() -> InMemoryRefreshTokenRepository:
    return InMemoryRefreshTokenRepository()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(repo, clock) -> TokenService:
    return TokenService(make_settings(), repo, clock)


def run(coro):
    return asyncio.run(coro)


def test_pair_matches_the_contract_and_stores_only_the_hash(service, repo):
    pair = run(service.issue_pair(USER))

    assert decode_access_token(pair.access_token, TEST_JWT_SECRET) == USER
    assert pair.token_type == "bearer"
    assert pair.expires_in == 900
    [row] = repo.rows.values()
    assert row.token_hash == hash_opaque_token(pair.refresh_token)
    assert pair.refresh_token not in row.token_hash


def test_rotation_revokes_the_old_token_and_slides_the_expiry(service, repo, clock):
    first = run(service.issue_pair(USER))
    clock.now += timedelta(days=10)

    second = run(service.rotate(first.refresh_token))

    old, new = repo.rows[1], repo.rows[2]
    assert old.revoked_at == clock.now
    assert old.replaced_by_id == new.id
    assert new.family_id == old.family_id
    assert new.expires_at == clock.now + timedelta(days=30)
    assert second.refresh_token != first.refresh_token
    assert repo.live() == [new]


def test_reused_token_revokes_the_whole_family(service, repo):
    first = run(service.issue_pair(USER))
    second = run(service.rotate(first.refresh_token))

    with pytest.raises(InvalidRefreshTokenError):
        run(service.rotate(first.refresh_token))
    with pytest.raises(InvalidRefreshTokenError):
        run(service.rotate(second.refresh_token))
    assert repo.live() == []


def test_reuse_leaves_other_sessions_alone(service, repo):
    phone = run(service.issue_pair(USER))
    tablet = run(service.issue_pair(USER))
    run(service.rotate(phone.refresh_token))

    with pytest.raises(InvalidRefreshTokenError):
        run(service.rotate(phone.refresh_token))
    run(service.rotate(tablet.refresh_token))


def test_lost_race_counts_as_reuse(service, repo):
    pair = run(service.issue_pair(USER))
    repo.replace_conflict = True

    with pytest.raises(InvalidRefreshTokenError):
        run(service.rotate(pair.refresh_token))
    assert repo.live() == []


def test_expired_refresh_token_is_rejected(service, clock):
    pair = run(service.issue_pair(USER))
    clock.now += timedelta(days=30)

    with pytest.raises(InvalidRefreshTokenError):
        run(service.rotate(pair.refresh_token))


def test_unknown_refresh_token_is_rejected(service):
    with pytest.raises(InvalidRefreshTokenError):
        run(service.rotate("made-up"))


def test_logout_revokes_the_family(service, repo):
    pair = run(service.issue_pair(USER))
    rotated = run(service.rotate(pair.refresh_token))

    run(service.logout(rotated.refresh_token, USER))

    assert repo.live() == []


def test_logout_with_an_already_rotated_own_token_revokes_the_family(service, repo):
    pair = run(service.issue_pair(USER))
    run(service.rotate(pair.refresh_token))

    run(service.logout(pair.refresh_token, USER))

    assert repo.live() == []


@pytest.mark.parametrize("token", ["foreign", "unknown"])
def test_logout_with_a_foreign_or_unknown_token_revokes_nothing(service, repo, token):
    mine = run(service.issue_pair(USER))
    theirs = run(service.issue_pair(OTHER_USER))
    presented = theirs.refresh_token if token == "foreign" else "made-up"

    with pytest.raises(InvalidRefreshTokenError):
        run(service.logout(presented, USER))

    assert len(repo.live()) == 2
    run(service.rotate(mine.refresh_token))


def test_revoke_all_ends_every_session_of_the_user_only(service, repo):
    run(service.issue_pair(USER))
    run(service.issue_pair(USER))
    theirs = run(service.issue_pair(OTHER_USER))

    run(service.revoke_all(USER))

    assert [row.user_id for row in repo.live()] == [OTHER_USER]
    run(service.rotate(theirs.refresh_token))


def test_missing_jwt_secret_fails_loudly(repo, clock):
    service = TokenService(make_settings(jwt_secret="too-short"), repo, clock)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        run(service.issue_pair(USER))
