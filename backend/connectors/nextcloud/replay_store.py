from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency guard
    redis = None


class ReplayStore(Protocol):
    async def mark_consumed(self, jti: str, ttl_seconds: int) -> bool:
        """Return True if this JTI was seen for the first time and is now consumed."""


@dataclass(slots=True)
class RedisReplayStore:
    redis_url: str
    namespace: str = "nextcloud-bridge:jti"

    def __post_init__(self) -> None:
        if redis is None:  # pragma: no cover - runtime guard
            raise RuntimeError(
                "redis.asyncio is not installed. Add 'redis>=5' to your dependencies."
            )
        self._client = redis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )

    def _key(self, jti: str) -> str:
        digest = hashlib.sha256(jti.encode("utf-8")).hexdigest()
        return f"{self.namespace}:{digest}"

    async def mark_consumed(self, jti: str, ttl_seconds: int) -> bool:
        key = self._key(jti)
        created = await self._client.set(key, "1", ex=ttl_seconds, nx=True)
        return bool(created)
