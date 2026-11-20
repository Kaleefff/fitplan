"""Settings from the environment and the repository `.env`, and the fixed photo limits.

The Gemini model, media resolution and thinking level are settings, so D-05 can change
them without a code change. GEMINI_API_KEY is a SecretStr: its repr and str are masked,
and nothing in this service logs it.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# ai-service/app/config.py -> the repository root; in the container this is / and the
# file does not exist, so only the environment (compose) is read
REPO_ROOT = Path(__file__).resolve().parents[2]

# Photo limits. MAX_PHOTO_BYTES equals the app's MAX_PHOTO_BYTES and RecognitionUpload
# ("at most 8 MB" = 8 MiB) in docs/api/openapi.yaml.
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_SIDE_PX = 1024  # longest side of the photo sent to Gemini; never upscaled
JPEG_QUALITY = 85
# Decompression bomb limit: 50 MP still admits photos of 50 MP phone cameras.
MAX_PIXELS = 50_000_000

# NFR-PERF: photo analysis within 10 s, so the Gemini budget (retry included) stays below
NFR_PERF_SECONDS = 10.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"

    # D25. Empty key or model: /predict and /health answer 503 not_configured.
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.1-flash-lite"
    # the whole Gemini call, the one retry included
    gemini_timeout_s: float = Field(default=7.0, gt=0, lt=NFR_PERF_SECONDS)
    gemini_media_resolution: Literal["low", "medium", "high"] = "medium"
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = "minimal"

    @property
    def configured(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value().strip() and self.gemini_model.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
