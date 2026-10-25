from app.core.rate_limit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_eleventh_request_in_the_window_is_limited():
    clock = Clock()
    limiter = RateLimiter(10, 60, clock)

    assert [limiter.hit("ip") for _ in range(10)] == [None] * 10
    clock.now += 15
    assert limiter.hit("ip") == 45


def test_window_slides():
    clock = Clock()
    limiter = RateLimiter(2, 60, clock)
    limiter.hit("ip")
    clock.now += 30
    limiter.hit("ip")

    clock.now += 30  # the first hit leaves the window
    assert limiter.hit("ip") is None
    assert limiter.hit("ip") == 30


def test_limited_requests_do_not_extend_the_block():
    clock = Clock()
    limiter = RateLimiter(1, 60, clock)
    limiter.hit("ip")
    for _ in range(5):
        limiter.hit("ip")

    clock.now += 60
    assert limiter.hit("ip") is None


def test_keys_are_independent():
    limiter = RateLimiter(1, 60, Clock())
    assert limiter.hit(("1.1.1.1", "/auth/login")) is None
    assert limiter.hit(("1.1.1.1", "/auth/register")) is None
    assert limiter.hit(("2.2.2.2", "/auth/login")) is None
    assert limiter.hit(("1.1.1.1", "/auth/login")) is not None
