"""Meal photo files under `PHOTO_DIR/meals/<user id>/` (DB-07, FR-N4, FR-U5).

The TTL index removes an expired recognition, so its `photoUrl` cannot be read any more.
A photo is therefore an orphan when nothing references it: no unexpired recognition, no
`nutrition_log.meal_photo_url`, and it is older than the TTL plus a grace period, so an
upload whose document is not written yet, or a confirm running right now, is never
touched (questions.md, DB-07). The same rule removes the leftovers of a failed
account-deletion step. Nothing is deleted when MongoDB or PostgreSQL cannot be read.
"""

import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pymongo.asynchronous.database import AsyncDatabase

from app.db.repositories.meal_recognitions import RECOGNITION_TTL, MongoMealRecognitionRepository

logger = logging.getLogger(__name__)

MEALS_SUBDIR = "meals"
PHOTO_CLEANUP_GRACE = timedelta(minutes=30)
PHOTO_CLEANUP_MIN_AGE = RECOGNITION_TTL + PHOTO_CLEANUP_GRACE

ConfirmedPhotoPaths = Callable[[], Awaitable[set[str]]]


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


async def _referenced_paths(
    recognitions_db: AsyncDatabase, confirmed_photo_paths: ConfirmedPhotoPaths, now: datetime
) -> set[str]:
    # MongoDB before PostgreSQL: a confirm writes the log first and deletes the document
    # after, so reading in this order sees the photo in at least one of the two.
    await recognitions_db.command("ping")
    repository = MongoMealRecognitionRepository(recognitions_db, clock=lambda: now)
    referenced = await repository.live_photo_urls()
    return referenced | await confirmed_photo_paths()


def _candidates(root: Path) -> list[Path]:
    """Regular files directly inside `root/meals/<user id>/`; links are never followed."""
    meals = root / MEALS_SUBDIR
    if _is_link(meals) or not meals.is_dir():
        return []
    files = []
    for user_dir in meals.iterdir():
        if _is_link(user_dir) or not user_dir.is_dir():
            continue
        files.extend(p for p in user_dir.iterdir() if not _is_link(p) and p.is_file())
    return files


async def cleanup_expired_photos(
    recognitions_db: AsyncDatabase,
    confirmed_photo_paths: ConfirmedPhotoPaths,
    photo_dir: Path,
    *,
    now: datetime | None = None,
    min_age: timedelta = PHOTO_CLEANUP_MIN_AGE,
) -> int:
    """Delete orphan meal photos; returns the number of files deleted. Idempotent (B-26)."""
    now = now or datetime.now(UTC)
    try:
        referenced = await _referenced_paths(recognitions_db, confirmed_photo_paths, now)
    except Exception as exc:
        logger.warning("Photo cleanup skipped, references unavailable: %s", type(exc).__name__)
        return 0

    root = photo_dir.resolve()
    cutoff = (now - min_age).timestamp()
    deleted = 0
    try:
        candidates = _candidates(root)
    except OSError as exc:
        logger.warning("Photo cleanup skipped, cannot list photos: %s", type(exc).__name__)
        return 0
    for path in candidates:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        if resolved.relative_to(root).as_posix() in referenced:
            continue
        try:
            if resolved.lstat().st_mtime >= cutoff:
                continue
            resolved.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("Photo cleanup could not delete a file: %s", type(exc).__name__)
            continue
        deleted += 1
    logger.info("Photo cleanup deleted %d files", deleted)
    return deleted


def delete_user_photos(photo_dir: Path, user_id: int) -> int:
    """Account deletion (B-05, FR-U5): remove `meals/<user id>/`; returns the files removed.

    A missing folder is a no-op. A folder that is a link is left alone, never followed.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TypeError("user_id must be an int")
    folder = photo_dir / MEALS_SUBDIR / str(user_id)
    if _is_link(folder):
        logger.warning("Photo folder of user %s is a link, not removed", user_id)
        return 0
    if not folder.is_dir():
        return 0
    count = sum(
        1
        for directory, _, names in os.walk(folder)
        for name in names
        if not _is_link(Path(directory, name))
    )
    shutil.rmtree(folder)
    logger.info("Deleted %d photos of user %s", count, user_id)
    return count
