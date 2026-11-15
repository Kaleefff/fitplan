"""The scheduler's photo cleanup job on MongoDB (B-26, FR-N4).

The orphan rule itself is tested in test_photo_cleanup.py; this checks that a pass of
the job wired as in `app.scheduler.main` removes an expired orphan and keeps a
confirmed photo. Skipped without MongoDB.
"""

from datetime import UTC, datetime

import pytest

from app.scheduler import photo_cleanup_job, run_pass
from tests.db.test_photo_cleanup import OLD, confirmed, photo, relative

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_a_pass_removes_an_expired_orphan_and_keeps_a_confirmed_photo(buffer_db, tmp_path):
    now = datetime.now(UTC)
    orphan = photo(tmp_path, 1, "orphan.jpg", OLD, now)
    kept = photo(tmp_path, 1, "confirmed.jpg", OLD, now)
    job = photo_cleanup_job(buffer_db, confirmed(relative(tmp_path, kept)), tmp_path)

    assert await run_pass([job]) == {"photo_cleanup": True}
    assert (orphan.exists(), kept.exists()) == (False, True)
    assert await run_pass([job]) == {"photo_cleanup": True}  # idempotent
