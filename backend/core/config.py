from __future__ import annotations

import base64
import hashlib
from functools import cached_property
from pathlib import Path
from typing import Literal, List

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
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

    APP_NAME: str = "NextCloud AI Server"
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    FRONTEND_URL:List[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])

    DATABASE_URL: str
    SQL_ECHO: bool = False
    SQL_POOL_SIZE: int = 10
    SQL_MAX_OVERFLOW: int = 20
    SQL_POOL_PRE_PING: bool = True

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    JWT_SECRET_KEY: SecretStr = Field(default=SecretStr("change-me"))
    SETTINGS_VAULT_KEY: SecretStr | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 8, ge=5, le=7 * 24 * 60)
    AUTH_ISSUER: str = "nextcloud-ai"
    AUTH_AUDIENCE: str = "nextcloud-ai-users"
    AUTH_COOKIE_NAME: str = "nc_ai_access_token"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    AUTH_COOKIE_DOMAIN: str | None = None

    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "ChangeMe123!"

    EMBEDDING_DIM: int = Field(default=768, ge=32, le=4096)
    EMBEDDING_PROVIDER: Literal["deterministic", "ollama"] = "deterministic"
    LLM_PROVIDER: Literal["stub", "ollama"] = "stub"
    OLLAMA_BASE_URL: AnyHttpUrl = Field(default="http://localhost:11434")
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_CHAT_MODEL: str = "llama3:8b-instruct"

    NEXTCLOUD_BRIDGE_SHARED_SECRET: SecretStr = Field(default=SecretStr("change-me"))
    NEXTCLOUD_BRIDGE_ISSUER: str = "nextcloud-bridge"
    NEXTCLOUD_BRIDGE_AUDIENCE: str = "fastapi-nextcloud"
    NEXTCLOUD_BRIDGE_TTL_SECONDS: int = Field(default=60, ge=15, le=300)
    NEXTCLOUD_BRIDGE_ALLOWED_CLOCK_SKEW_SECONDS: int = Field(default=15, ge=0, le=60)
    NEXTCLOUD_BRIDGE_REDIS_URL: str | None = None
    NEXTCLOUD_WEBHOOK_SECRET: SecretStr | None = None
    NEXTCLOUD_VERIFY_TLS: bool = True
    NEXTCLOUD_REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, ge=1.0, le=120.0)

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().strip("'\"")
        if not normalized:
            raise ValueError("DATABASE_URL is empty")
        make_url(normalized)
        return normalized

    @field_validator("FRONTEND_URL", mode="after")
    @classmethod
    def strip_frontend_urls(cls, values: List[str]) -> List[str]:
        return [url.rstrip("/") for url in values]

    @cached_property
    def effective_celery_broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @cached_property
    def effective_celery_result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    @cached_property
    def auth_cookie_max_age(self) -> int:
        return self.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    @cached_property
    def vault_fernet_key(self) -> bytes:
        raw = (
            (self.SETTINGS_VAULT_KEY or self.JWT_SECRET_KEY)
            .get_secret_value()
            .encode("utf-8")
        )
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)


settings = Settings()
