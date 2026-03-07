from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "AI SERVER"
    APP_ENV: str = "development"
    DEBUG: bool = True

    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str
    SQL_ECHO: bool = False
    SQL_POOL_SIZE: int = 10
    SQL_MAX_OVERFLOW: int = 20
    SQL_POOL_PRE_PING: bool = True

    EMBEDDING_DIM: int = 768

    JWT_SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    ALGORITHM: str = "HS256"

    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "ChangeMe123!"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().strip("'\"")
        if not normalized:
            raise ValueError("DATABASE_URL is empty")

        try:
            make_url(normalized)
        except Exception as exc:
            raise ValueError(
                "DATABASE_URL must be a valid SQLAlchemy URL like "
                "'postgresql+asyncpg://user:pass@host:5432/dbname'"
            ) from exc

        return normalized


settings = Settings()
