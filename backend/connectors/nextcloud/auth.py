from __future__ import annotations

import time
import uuid
from typing import Any

import jwt

from backend.connectors.nextcloud.config import NextcloudBridgeSettings
from backend.connectors.nextcloud.exceptions import BridgeTokenError
from backend.connectors.nextcloud.replay_store import ReplayStore
from backend.connectors.nextcloud.schemas import BridgeTokenClaims


class BridgeTokenCodec:
    def __init__(
        self, settings: NextcloudBridgeSettings, replay_store: ReplayStore | None = None
    ) -> None:
        self.settings = settings
        self.replay_store = replay_store

    def issue_token(
        self,
        *,
        sub: str,
        username: str,
        nc_base_url: str,
        display_name: str | None = None,
        email: str | None = None,
        groups: list[str] | None = None,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": self.settings.bridge_issuer,
            "aud": self.settings.bridge_audience,
            "sub": sub,
            "preferred_username": username,
            "display_name": display_name,
            "email": email,
            "groups": groups or [],
            "provider": "nextcloud",
            "nc_base_url": nc_base_url,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "nbf": now,
            "exp": now + self.settings.bridge_ttl_seconds,
        }
        return jwt.encode(
            payload,
            self.settings.bridge_shared_secret.get_secret_value(),
            algorithm="HS256",
        )

    async def verify_and_consume(self, token: str) -> BridgeTokenClaims:
        try:
            decoded = jwt.decode(
                token,
                self.settings.bridge_shared_secret.get_secret_value(),
                algorithms=["HS256"],
                audience=self.settings.bridge_audience,
                issuer=self.settings.bridge_issuer,
                leeway=self.settings.allowed_clock_skew_seconds,
                options={"require": ["iss", "aud", "sub", "jti", "iat", "nbf", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise BridgeTokenError(f"Invalid bridge token: {exc}") from exc

        claims = BridgeTokenClaims.model_validate(decoded)
        if self.replay_store is not None:
            ttl = max(claims.exp - int(time.time()), 1)
            accepted = await self.replay_store.mark_consumed(
                claims.jti, ttl_seconds=ttl
            )
            if not accepted:
                raise BridgeTokenError("Replay detected for bridge token")
        return claims
