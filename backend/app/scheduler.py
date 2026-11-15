"""Scheduler process (B-26; FR-N4 cleanup, FR-R7): `python -m app.scheduler`.

One process runs every job once at start and then every 15 minutes, timed from the
start of each pass. Jobs are idempotent, so a pass repeated after a restart or a crash
does no harm; a failing job is logged and the others still run. Core job: the meal
photo cleanup (`mongo_buffer.md` "Photo cleanup"). The weekly report and push
delivery are stretch S-03.
"""

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.photo_cleanup import ConfirmedPhotoPaths, cleanup_expired_photos
from app.db.repositories.nutrition_photos import SqlConfirmedPhotoPaths
from app.db.session import get_async_engine
from app.domain.constants import SCHEDULER_INTERVAL_SECONDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    name: str
    run: Callable[[], Awaitable[object]]


def photo_cleanup_job(
    recognitions_db: AsyncDatabase, confirmed_photo_paths: ConfirmedPhotoPaths, photo_dir: Path
) -> Job:
    async def run() -> int:
        return await cleanup_expired_photos(recognitions_db, confirmed_photo_paths, photo_dir)

    return Job("photo_cleanup", run)


async def run_pass(jobs: Sequence[Job]) -> dict[str, bool]:
    """Runs every job once, in order; returns which ones finished without an error."""
    finished = {}
    for job in jobs:
        try:
            await job.run()
            finished[job.name] = True
        except Exception as exc:  # one failing job never stops the others
            logger.error("Scheduler job %s failed: %s", job.name, type(exc).__name__)
            finished[job.name] = False
    return finished


async def run_forever(
    jobs: Sequence[Job],
    stop: asyncio.Event,
    *,
    interval: float = SCHEDULER_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Runs a pass now and then every `interval` seconds until `stop` is set; a pass
    longer than the interval starts the next one at once. Returns the passes run."""
    passes = 0
    while not stop.is_set():
        started = clock()
        await run_pass(jobs)
        passes += 1
        delay = max(0.0, started + interval - clock())
        with contextlib.suppress(TimeoutError):  # the interval is over: next pass
            await asyncio.wait_for(stop.wait(), timeout=delay)
    return passes


async def main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    photo_dir = settings.photo_root()  # fails at start when PHOTO_DIR is not set
    mongo = AsyncMongoClient(
        **settings.mongo_client_kwargs(),
        serverSelectionTimeoutMS=int(settings.health_check_timeout_seconds * 1000),
    )
    engine = get_async_engine()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    jobs = [
        photo_cleanup_job(mongo[settings.mongo_db], SqlConfirmedPhotoPaths(sessions), photo_dir)
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    logger.info("Scheduler started: %d job(s) every %d s", len(jobs), SCHEDULER_INTERVAL_SECONDS)
    try:
        await run_forever(jobs, stop)
    finally:
        await mongo.close()
        await engine.dispose()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
