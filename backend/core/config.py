from __future__ import annotations

import base64
import hashlib
import json
from functools import cached_property
from pathlib import Path
from typing import List, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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
    FRONTEND_URL: str | List[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )

    DATABASE_URL: str
    SQL_ECHO: bool = False
    SQL_POOL_SIZE: int = 10
    SQL_MAX_OVERFLOW: int = 20
    SQL_POOL_PRE_PING: bool = True

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None
    CELERY_TASK_ALWAYS_EAGER: bool | None = None

    JWT_SECRET_KEY: SecretStr = Field(default=SecretStr("change-me"))
    SETTINGS_VAULT_KEY: SecretStr | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 8, ge=5, le=7 * 24 * 60)
    AUTH_ISSUER: str = "nextcloud-ai"
    AUTH_AUDIENCE: str = "nextcloud-ai-users"
    AUTH_COOKIE_NAME: str = "nc_ai_access_token"
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    AUTH_COOKIE_DOMAIN: str | None = None
    CSRF_COOKIE_NAME: str = "nc_ai_csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    CSRF_COOKIE_SECURE: bool | None = None
    CSRF_COOKIE_SAMESITE: Literal["lax", "strict", "none"] | None = None

    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "ChangeMe123!"

    EMBEDDING_DIM: int
    EMBEDDING_PROVIDER: Literal["deterministic", "ollama"] | None = None
    LLM_PROVIDER: Literal["stub", "ollama"] | None = None
    OLLAMA_BASE_URL: AnyHttpUrl = Field(default="http://localhost:11434")
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3:latest"
    OLLAMA_CHAT_MODEL: str = "llama3:latest"
    OLLAMA_READINESS_TIMEOUT_SECONDS: float = Field(default=5.0, ge=1.0, le=60.0)
    OLLAMA_PULL_TIMEOUT_SECONDS: float = Field(default=900.0, ge=30.0, le=3600.0)
    OLLAMA_WARMUP_TIMEOUT_SECONDS: float = Field(default=120.0, ge=5.0, le=900.0)

    CHAT_VERIFICATION_SHADOW_MODE: bool = False

    RAG_GRAPH_EXPANSION_ENABLED: bool = True
    RAG_GRAPH_EXPANSION_MAX_SEED_DOCUMENTS: int = Field(default=4, ge=1, le=20)
    RAG_SESSION_SUMMARY_MESSAGE_THRESHOLD: int = Field(default=14, ge=6, le=200)
    RAG_EVAL_METRICS_LOG_PATH: str | None = None

    PRODUCT_INTELLIGENCE_ENABLED: bool = True
    PRODUCT_INTELLIGENCE_EXTRACTION_MODE: Literal["off", "inline", "async"] = "inline"

    NEXTCLOUD_BRIDGE_SHARED_SECRET: SecretStr = Field(default=SecretStr("change-me"))
    NEXTCLOUD_BRIDGE_ISSUER: str = "nextcloud-bridge"
    NEXTCLOUD_BRIDGE_AUDIENCE: str = "fastapi-nextcloud"
    NEXTCLOUD_BRIDGE_TTL_SECONDS: int = Field(default=60, ge=15, le=300)
    NEXTCLOUD_BRIDGE_ALLOWED_CLOCK_SKEW_SECONDS: int = Field(default=15, ge=0, le=60)
    NEXTCLOUD_BRIDGE_REDIS_URL: str | None = None
    NEXTCLOUD_WEBHOOK_SECRET: SecretStr | None = None
    NEXTCLOUD_VERIFY_TLS: bool = True
    NEXTCLOUD_REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, ge=1.0, le=120.0)
    NEXTCLOUD_WEBHOOK_DEBOUNCE_SECONDS: int = Field(default=30, ge=1, le=3600)
    NEXTCLOUD_FALLBACK_SYNC_INTERVAL_SECONDS: int = Field(
        default=300, ge=30, le=86400
    )
    NEXTCLOUD_FALLBACK_STALE_AFTER_SECONDS: int = Field(
        default=900, ge=60, le=604800
    )
    EMAIL_CONNECTOR_FETCH_LIMIT: int = Field(default=100, ge=1, le=500)
    EMAIL_INLINE_BLOB_MAX_BYTES: int = Field(default=2_000_000, ge=4096, le=20_000_000)
    TASK_WEBHOOK_URL: str | None = None
    TASK_WEBHOOK_TIMEOUT_SECONDS: float = Field(default=10.0, ge=1.0, le=120.0)

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"
    REQUEST_ID_HEADER_NAME: str = "X-Request-ID"
    TRACE_ID_HEADER_NAME: str = "X-Trace-ID"

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

    @field_validator("FRONTEND_URL", mode="before")
    @classmethod
    def normalize_frontend_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        if normalized.startswith("'[") and normalized.endswith("]'"):
            normalized = normalized[1:-1]
        elif normalized.startswith('"[') and normalized.endswith(']"'):
            normalized = normalized[1:-1]

        if normalized.startswith("[") and normalized.endswith("]"):
            parsed = json.loads(normalized)
            if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                return parsed

        return normalized.strip("'\"")

    @field_validator("OLLAMA_CHAT_MODEL", "OLLAMA_EMBEDDING_MODEL", mode="before")
    @classmethod
    def normalize_ollama_model_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Ollama model name cannot be empty")
        return normalized

    @field_validator("FRONTEND_URL", mode="after")
    @classmethod
    def strip_frontend_urls(cls, values: str | List[str]) -> str | List[str]:
        if isinstance(values, str):
            return values.rstrip("/")
        return [url.rstrip("/") for url in values]

    @cached_property
    def frontend_allowed_origins(self) -> List[str]:
        if isinstance(self.FRONTEND_URL, str):
            return [self.FRONTEND_URL]
        return self.FRONTEND_URL

    @cached_property
    def frontend_redirect_url(self) -> str:
        if isinstance(self.FRONTEND_URL, str):
            return self.FRONTEND_URL
        if not self.FRONTEND_URL:
            raise ValueError("FRONTEND_URL must contain at least one URL")
        return self.FRONTEND_URL[-1]

    @cached_property
    def effective_celery_broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @cached_property
    def effective_celery_result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    @cached_property
    def celery_task_always_eager(self) -> bool:
        if self.CELERY_TASK_ALWAYS_EAGER is not None:
            return self.CELERY_TASK_ALWAYS_EAGER
        return self.APP_ENV == "development"

    @cached_property
    def nextcloud_event_redis_url(self) -> str:
        return self.NEXTCLOUD_BRIDGE_REDIS_URL or self.REDIS_URL

    @cached_property
    def effective_embedding_provider(self) -> Literal["deterministic", "ollama"]:
        if self.EMBEDDING_PROVIDER is not None:
            return self.EMBEDDING_PROVIDER
        if self.APP_ENV in {"staging", "production"}:
            return "ollama"
        return "deterministic"

    @cached_property
    def effective_llm_provider(self) -> Literal["stub", "ollama"]:
        if self.LLM_PROVIDER is not None:
            return self.LLM_PROVIDER
        if self.APP_ENV in {"staging", "production"}:
            return "ollama"
        return "stub"

    @cached_property
    def ollama_required(self) -> bool:
        return (
            self.effective_embedding_provider == "ollama"
            or self.effective_llm_provider == "ollama"
        )

    @cached_property
    def auth_cookie_max_age(self) -> int:
        return self.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    @cached_property
    def auth_cookie_secure(self) -> bool:
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.APP_ENV in {"staging", "production"}

    @cached_property
    def csrf_cookie_secure(self) -> bool:
        if self.CSRF_COOKIE_SECURE is not None:
            return self.CSRF_COOKIE_SECURE
        return self.auth_cookie_secure

    @cached_property
    def csrf_cookie_samesite(self) -> Literal["lax", "strict", "none"]:
        return self.CSRF_COOKIE_SAMESITE or self.AUTH_COOKIE_SAMESITE

    @cached_property
    def vault_fernet_key(self) -> bytes:
        raw = (
            (self.SETTINGS_VAULT_KEY or self.JWT_SECRET_KEY)
            .get_secret_value()
            .encode("utf-8")
        )
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.APP_ENV in {"staging", "production"} and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be enabled outside development/test")
        if self.AUTH_COOKIE_SAMESITE == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SAMESITE='none' requires AUTH_COOKIE_SECURE")
        if self.csrf_cookie_samesite == "none" and not self.csrf_cookie_secure:
            raise ValueError("CSRF_COOKIE_SAMESITE='none' requires CSRF_COOKIE_SECURE")
        return self


settings = Settings()
