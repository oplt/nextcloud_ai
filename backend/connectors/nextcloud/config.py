from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl, BaseModel, SecretStr

from backend.core.config import settings


class NextcloudBridgeSettings(BaseModel):
    bridge_shared_secret: SecretStr
    bridge_issuer: str
    bridge_audience: str
    bridge_ttl_seconds: int
    allowed_clock_skew_seconds: int
    bridge_redis_url: str | None = None
    webhook_secret: SecretStr | None = None
    verify_tls: bool = True
    request_timeout_seconds: float = 30.0


class NextcloudConnectorConfig(BaseModel):
    base_url: AnyHttpUrl
    username: str
    app_password: SecretStr
    root_path: str = "/"
    verify_tls: bool = True
    request_timeout_seconds: float = 30.0


@lru_cache(maxsize=1)
def get_nextcloud_settings() -> NextcloudBridgeSettings:
    return NextcloudBridgeSettings(
        bridge_shared_secret=settings.NEXTCLOUD_BRIDGE_SHARED_SECRET,
        bridge_issuer=settings.NEXTCLOUD_BRIDGE_ISSUER,
        bridge_audience=settings.NEXTCLOUD_BRIDGE_AUDIENCE,
        bridge_ttl_seconds=settings.NEXTCLOUD_BRIDGE_TTL_SECONDS,
        allowed_clock_skew_seconds=settings.NEXTCLOUD_BRIDGE_ALLOWED_CLOCK_SKEW_SECONDS,
        bridge_redis_url=settings.NEXTCLOUD_BRIDGE_REDIS_URL,
        webhook_secret=settings.NEXTCLOUD_WEBHOOK_SECRET,
        verify_tls=settings.NEXTCLOUD_VERIFY_TLS,
        request_timeout_seconds=settings.NEXTCLOUD_REQUEST_TIMEOUT_SECONDS,
    )
