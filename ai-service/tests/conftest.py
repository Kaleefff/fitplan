"""Shared helpers: photos built in memory and explicit settings.

No test reads .env (every Settings is built with _env_file=None) and none calls Gemini:
the provider tests use a fake client, the endpoint tests a fake provider.
"""

import io

import pytest
from PIL import Image

from app.config import Settings

# a fake key; tests assert it never shows up in logs, errors or reprs
TEST_KEY = "test-key-0123456789-must-not-leak"
TEST_MODEL = "gemini-test"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"gemini_api_key": TEST_KEY, "gemini_model": TEST_MODEL}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_photo(
    fmt: str = "JPEG",
    size: tuple[int, int] = (300, 200),
    mode: str = "RGB",
    color: tuple[int, ...] | int = (200, 80, 40),
    **save_args: object,
) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, format=fmt, **save_args)
    return out.getvalue()


def open_photo(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image
