"""In-process sliding-window rate limit for the auth routes (api-rules.md "Auth and account").

Per process only; the hard limit is at the reverse proxy.
"""

import math
import time
from collections import deque
from collections.abc import Callable, Hashable


class RateLimiter:
    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}

    def hit(self, key: Hashable) -> int | None:
        """Counts a request; returns the seconds to wait (Retry-After) when over the limit."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return max(1, math.ceil(hits[0] + self._window - now))
        hits.append(now)
        return None
