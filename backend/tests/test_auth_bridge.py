from __future__ import annotations

import pytest
from pydantic import SecretStr

from backend.connectors.nextcloud.auth import BridgeTokenCodec
from backend.connectors.nextcloud.config import NextcloudBridgeSettings
from backend.connectors.nextcloud.exceptions import BridgeTokenError


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
