"""Application settings, read from the environment and the repository `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

# HS256 keys shorter than the hash output are rejected (RFC 7518, 3.2)
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # Same variable names as docker-compose.yml and .env.example
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "fitplan"
    postgres_user: str = "fitplan"
    postgres_password: SecretStr = SecretStr("")

    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_db: str = "fitplan"
    mongo_user: str = "fitplan"
    mongo_password: SecretStr = SecretStr("")

    health_check_timeout_seconds: float = 2.0

    # Auth (api-rules.md "Auth and account"). JWT_SECRET has no default on purpose.
    jwt_secret: SecretStr = SecretStr("")
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    bcrypt_rounds: int = 12
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60

    def jwt_signing_key(self) -> str:
        key = self.jwt_secret.get_secret_value()
        if len(key.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
            raise RuntimeError(f"JWT_SECRET must be set to at least {MIN_JWT_SECRET_BYTES} bytes")
        return key

    # Hardening (api-rules.md). Native Android sends no Origin; list web origins as JSON,
    # e.g. CORS_ORIGINS='["http://localhost:8081"]' for Expo web.
    cors_origins: list[str] = []
    max_body_bytes: int = 1024 * 1024
    max_upload_body_bytes: int = 9 * 1024 * 1024

    def mongo_client_kwargs(self) -> dict[str, object]:
        """Keyword arguments for pymongo.AsyncMongoClient (D18)."""
        return {
            "host": self.mongo_host,
            "port": self.mongo_port,
            "username": self.mongo_user,
            "password": self.mongo_password.get_secret_value(),
            "authSource": "admin",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
