from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NextcloudSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXTCLOUD_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: AnyHttpUrl = Field(..., description="Base URL of the Nextcloud instance")
    service_user: str = Field(..., description="Dedicated Nextcloud technical account")
    service_password: SecretStr = Field(..., description="App password for the technical account")

    bridge_shared_secret: SecretStr = Field(
        ..., description="Shared HMAC secret between Nextcloud PHP app and FastAPI"
    )
    bridge_issuer: str = Field(default="nextcloud-bridge")
    bridge_audience: str = Field(default="fastapi-nextcloud")
    bridge_ttl_seconds: int = Field(default=60, ge=15, le=300)
    allowed_clock_skew_seconds: int = Field(default=15, ge=0, le=60)
    bridge_redis_url: str | None = Field(default=None)

    webhook_secret: SecretStr | None = Field(
        default=None, description="Optional secret for incoming webhook payloads"
    )

    verify_tls: bool = True
    request_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)


@lru_cache(maxsize=1)
def get_nextcloud_settings() -> NextcloudSettings:
    return NextcloudSettings()
