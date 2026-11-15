"""The scheduler loop (B-26): passes, intervals, failing jobs, stopping. No Docker."""

import asyncio
import itertools

import anyio
import pytest

from app.scheduler import Job, run_forever, run_pass

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def counting(name: str, calls: list[str], fail: bool = False) -> Job:
    async def run() -> None:
        calls.append(name)
        if fail:
            raise RuntimeError("boom")

    return Job(name, run)


async def test_a_failing_job_does_not_stop_the_others():
    calls: list[str] = []

    finished = await run_pass([counting("a", calls, fail=True), counting("b", calls)])

    assert calls == ["a", "b"]
    assert finished == {"a": False, "b": True}


async def test_passes_repeat_until_stopped():
    stop = asyncio.Event()
    calls: list[str] = []

    async def third_stops() -> None:
        calls.append("job")
        if len(calls) == 3:
            stop.set()

    with anyio.fail_after(2):
        passes = await run_forever([Job("job", third_stops)], stop, interval=0.01)

    assert passes == 3


async def test_a_pass_longer_than_the_interval_starts_the_next_at_once():
    stop = asyncio.Event()
    ticks = itertools.count(step=100)  # every clock read is 100 s later than the last
    calls: list[str] = []

    async def slow() -> None:
        calls.append("job")
        if len(calls) == 2:
            stop.set()

    with anyio.fail_after(2):  # with a 60 s interval it would hang if it waited
        await run_forever([Job("job", slow)], stop, interval=60, clock=lambda: next(ticks))

    assert calls == ["job", "job"]


async def test_stop_ends_the_wait_between_passes():
    stop = asyncio.Event()
    calls: list[str] = []

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    with anyio.fail_after(2):  # the interval is an hour
        stopper = asyncio.create_task(stop_soon())
        passes = await run_forever([counting("job", calls)], stop, interval=3600)
        await stopper

    assert (passes, calls) == (1, ["job"])
