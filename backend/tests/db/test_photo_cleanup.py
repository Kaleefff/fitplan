"""Meal photo cleanup and account photo deletion (DB-07, FR-N4, FR-U5).

Files live in `tmp_path`; recognitions in `buffer_db` (tests/db/conftest.py; those
tests skip without MongoDB). The unreachable-store and `delete_user_photos` tests need
no Docker.
"""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.db.photo_cleanup import (
    PHOTO_CLEANUP_GRACE,
    PHOTO_CLEANUP_MIN_AGE,
    cleanup_expired_photos,
    delete_user_photos,
)
from app.db.repositories.meal_recognitions import (
    COLLECTION,
    RECOGNITION_TTL,
    MongoMealRecognitionRepository,
    RecognitionModel,
)

OLD = PHOTO_CLEANUP_MIN_AGE + timedelta(minutes=1)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def photo(root: Path, user_id: int, name: str, age: timedelta, now: datetime) -> Path:
    path = root / "meals" / str(user_id) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8 jpeg")
    stamp = (now - age).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def confirmed(*paths: str):
    async def confirmed_photo_paths() -> set[str]:
        return set(paths)

    return confirmed_photo_paths


async def recognition(db, user_id: int, photo_url: str, created: datetime) -> None:
    await MongoMealRecognitionRepository(db, clock=lambda: created).create(
        user_id=user_id,
        meal_type="dinner",
        photo_url=photo_url,
        model=RecognitionModel("food101-vit", "1.0"),
        overall_confidence=0.5,
        items=[],
    )


# ---------------------------------------------------------------- orphan rule


async def test_unreferenced_old_file_is_deleted(buffer_db, tmp_path):
    now = datetime.now(UTC)
    orphan = photo(tmp_path, 1, "orphan.jpg", OLD, now)

    assert await cleanup_expired_photos(buffer_db, confirmed(), tmp_path, now=now) == 1
    assert not orphan.exists()
    assert await cleanup_expired_photos(buffer_db, confirmed(), tmp_path, now=now) == 0


async def test_file_of_an_unexpired_recognition_is_kept(buffer_db, tmp_path):
    now = datetime.now(UTC)
    kept = photo(tmp_path, 1, "pending.jpg", OLD, now)
    await recognition(buffer_db, 1, relative(tmp_path, kept), created=now)

    assert await cleanup_expired_photos(buffer_db, confirmed(), tmp_path, now=now) == 0
    assert kept.exists()


async def test_file_of_an_expired_recognition_is_deleted(buffer_db, tmp_path):
    created = datetime.now(UTC)  # real expiresAt in the future: the TTL monitor keeps it
    later = created + RECOGNITION_TTL + PHOTO_CLEANUP_GRACE + timedelta(minutes=5)
    expired = photo(tmp_path, 1, "expired.jpg", later - created, later)
    await recognition(buffer_db, 1, relative(tmp_path, expired), created=created)

    assert await cleanup_expired_photos(buffer_db, confirmed(), tmp_path, now=later) == 1
    assert not expired.exists()
    assert await buffer_db[COLLECTION].count_documents({}) == 1  # deleted by expiry, not TTL


async def test_confirmed_photo_is_kept(buffer_db, tmp_path):
    now = datetime.now(UTC)
    kept = photo(tmp_path, 1, "confirmed.jpg", timedelta(days=90), now)
    orphan = photo(tmp_path, 1, "orphan.jpg", OLD, now)

    paths = confirmed(relative(tmp_path, kept))
    assert await cleanup_expired_photos(buffer_db, paths, tmp_path, now=now) == 1
    assert kept.exists() and not orphan.exists()


@pytest.mark.parametrize(
    "age",
    [
        timedelta(minutes=1),
        RECOGNITION_TTL + PHOTO_CLEANUP_GRACE / 2,
        PHOTO_CLEANUP_MIN_AGE - timedelta(seconds=1),
    ],
    ids=["fresh", "inside-grace", "just-under-min-age"],
)
async def test_file_younger_than_min_age_is_kept(buffer_db, tmp_path, age):
    now = datetime.now(UTC)
    young = photo(tmp_path, 1, "young.jpg", age, now)

    assert await cleanup_expired_photos(buffer_db, confirmed(), tmp_path, now=now) == 0
    assert young.exists()


async def test_min_age_parameter_is_honoured(buffer_db, tmp_path):
    now = datetime.now(UTC)
    path = photo(tmp_path, 1, "a.jpg", timedelta(minutes=10), now)

    deleted = await cleanup_expired_photos(
        buffer_db, confirmed(), tmp_path, now=now, min_age=timedelta(minutes=5)
    )
    assert deleted == 1 and not path.exists()


async def test_files_of_every_user_folder_are_checked(buffer_db, tmp_path):
    now = datetime.now(UTC)
    first = photo(tmp_path, 1, "a.jpg", OLD, now)
    second = photo(tmp_path, 2, "b.jpg", OLD, now)
    kept = photo(tmp_path, 3, "c.jpg", OLD, now)

    paths = confirmed(relative(tmp_path, kept))
    assert await cleanup_expired_photos(buffer_db, paths, tmp_path, now=now) == 2
    assert not first.exists() and not second.exists() and kept.exists()
    assert first.parent.is_dir()  # empty user folders stay (questions.md, DB-07)


async def test_missing_photo_dir_deletes_nothing(buffer_db, tmp_path):
    missing = tmp_path / "no-such-dir"

    assert await cleanup_expired_photos(buffer_db, confirmed(), missing) == 0
    assert not missing.exists()


# ---------------------------------------------------------------- stores unavailable


async def test_unreachable_mongo_deletes_nothing(tmp_path):
    now = datetime.now(UTC)
    orphan = photo(tmp_path, 1, "orphan.jpg", OLD, now)
    calls = []

    async def confirmed_photo_paths() -> set[str]:
        calls.append(1)
        return set()

    unreachable = Settings(mongo_port=1)  # port 1 is never served
    client = AsyncMongoClient(**unreachable.mongo_client_kwargs(), serverSelectionTimeoutMS=300)
    try:
        deleted = await cleanup_expired_photos(
            client[unreachable.mongo_db], confirmed_photo_paths, tmp_path, now=now
        )
    finally:
        await client.close()

    assert deleted == 0
    assert orphan.exists()
    assert calls == []  # PostgreSQL is not even asked


async def test_failing_confirmed_photo_paths_deletes_nothing(buffer_db, tmp_path):
    now = datetime.now(UTC)
    orphan = photo(tmp_path, 1, "orphan.jpg", OLD, now)

    async def postgres_down() -> set[str]:
        raise ConnectionError("PostgreSQL is down")

    assert await cleanup_expired_photos(buffer_db, postgres_down, tmp_path, now=now) == 0
    assert orphan.exists()


# ---------------------------------------------------------------- links


def symlink(link: Path, target: Path, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not permitted here (Windows without Developer Mode)")


async def test_symlinks_are_skipped(buffer_db, tmp_path):
    now = datetime.now(UTC)
    photo_dir = tmp_path / "photos"
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.jpg"
    secret.write_bytes(b"x")
    stamp = (now - OLD).timestamp()
    os.utime(secret, (stamp, stamp))
    orphan = photo(photo_dir, 1, "orphan.jpg", OLD, now)

    file_link = photo_dir / "meals" / "1" / "link.jpg"
    symlink(file_link, secret)
    folder_link = photo_dir / "meals" / "2"
    symlink(folder_link, outside, target_is_directory=True)

    assert await cleanup_expired_photos(buffer_db, confirmed(), photo_dir, now=now) == 1
    assert not orphan.exists()
    assert file_link.is_symlink() and folder_link.is_symlink()
    assert secret.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions exist only on Windows")
async def test_junctions_are_skipped(buffer_db, tmp_path):
    import _winapi  # Windows only; needs no privilege, unlike a symlink

    now = datetime.now(UTC)
    photo_dir = tmp_path / "photos"
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.jpg"
    secret.write_bytes(b"x")
    stamp = (now - OLD).timestamp()
    os.utime(secret, (stamp, stamp))
    orphan = photo(photo_dir, 1, "orphan.jpg", OLD, now)
    junction = photo_dir / "meals" / "2"
    _winapi.CreateJunction(str(outside), str(junction))

    assert await cleanup_expired_photos(buffer_db, confirmed(), photo_dir, now=now) == 1
    assert not orphan.exists()
    assert secret.exists()
    assert delete_user_photos(photo_dir, 2) == 0  # a linked user folder is never followed
    assert secret.exists()


# ---------------------------------------------------------------- account deletion


def test_delete_user_photos_on_a_missing_folder_is_a_no_op(tmp_path):
    assert delete_user_photos(tmp_path, 1) == 0
    assert delete_user_photos(tmp_path / "no-such-dir", 1) == 0


def test_delete_user_photos_removes_the_users_folder_only(tmp_path):
    now = datetime.now(UTC)
    for name in ("a.jpg", "b.png", "c.webp"):
        photo(tmp_path, 1, name, timedelta(0), now)
    other = photo(tmp_path, 2, "d.jpg", timedelta(0), now)

    assert delete_user_photos(tmp_path, 1) == 3
    assert not (tmp_path / "meals" / "1").exists()
    assert other.exists()
    assert delete_user_photos(tmp_path, 1) == 0


@pytest.mark.parametrize("bad_id", ["1", "../2", True, 1.0])
def test_delete_user_photos_takes_only_an_int_id(tmp_path, bad_id):
    other = photo(tmp_path, 2, "d.jpg", timedelta(0), datetime.now(UTC))

    with pytest.raises(TypeError):
        delete_user_photos(tmp_path, bad_id)
    assert other.exists()
