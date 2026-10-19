"""Application settings, read from the environment and the repository `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


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

    def postgres_conninfo(self) -> str:
        """libpq connection string for psycopg (D17)."""
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password.get_secret_value()}"
        )

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
