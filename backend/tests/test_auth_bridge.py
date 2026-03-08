from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from backend.api.v1 import nextcloud_auth
from backend.connectors.nextcloud.auth import BridgeTokenCodec
from backend.connectors.nextcloud.config import NextcloudBridgeSettings
from backend.connectors.nextcloud.exceptions import BridgeTokenError
from backend.core.config import settings
from backend.schemas.auth_schema import AuthSessionResponse
from backend.schemas.user_schema import UserRead


class FakeReplayStore:
    def __init__(self) -> None:
        self.consumed: set[str] = set()

    async def mark_consumed(self, jti: str, ttl_seconds: int) -> bool:
        if jti in self.consumed:
            return False
        self.consumed.add(jti)
        return True


@pytest.mark.asyncio
async def test_bridge_token_is_single_use() -> None:
    codec = BridgeTokenCodec(
        settings=NextcloudBridgeSettings(
            bridge_shared_secret=SecretStr("super-secret-key-for-tests-123456"),
            bridge_issuer="nextcloud-bridge",
            bridge_audience="fastapi-nextcloud",
            bridge_ttl_seconds=60,
            allowed_clock_skew_seconds=0,
        ),
        replay_store=FakeReplayStore(),
    )

    token = codec.issue_token(
        sub="alice",
        username="alice",
        nc_base_url="https://nextcloud.local",
        groups=["staff"],
    )

    claims = await codec.verify_and_consume(token)
    assert claims.sub == "alice"
    with pytest.raises(BridgeTokenError):
        await codec.verify_and_consume(token)


@pytest.mark.asyncio
async def test_sso_consume_returns_html_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_exchange_principal(session, principal: object) -> AuthSessionResponse:
        now = datetime.now(timezone.utc)
        return AuthSessionResponse(
            access_token="bridge-session-token",
            expires_in=3600,
            user=UserRead(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                auth_provider="nextcloud",
                username="alice",
                email="alice@example.com",
                full_name="Alice",
                nextcloud_base_url="http://localhost",
                last_login_at=now,
                is_active=True,
                is_superuser=False,
                role=None,
            ),
        )

    class DummyCodec:
        async def verify_and_consume(self, bridge_token: str) -> object:
            assert bridge_token == "bridge-token"
            return SimpleNamespace(
                sub="alice",
                preferred_username="alice",
                display_name="Alice",
                email="alice@example.com",
                groups=["users"],
                nc_base_url="http://localhost",
            )

    monkeypatch.setattr(nextcloud_auth, "_exchange_principal", fake_exchange_principal)

    response = await nextcloud_auth.consume_nextcloud_bridge_token(
        bridge_token="bridge-token",
        session=None,
        codec=DummyCodec(),
    )

    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert settings.AUTH_COOKIE_NAME in response.headers["set-cookie"]
    assert settings.frontend_redirect_url in body
    assert "window.location.replace" in body
