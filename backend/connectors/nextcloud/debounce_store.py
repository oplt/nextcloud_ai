from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency guard
    redis = None


class DebounceStore(Protocol):
    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        """Return True when a debounce slot is acquired for the first time."""


@dataclass(slots=True)
class RedisDebounceStore:
    redis_url: str
    namespace: str = "nextcloud:webhooks"

    def __post_init__(self) -> None:
        if redis is None:  # pragma: no cover - runtime guard
            raise RuntimeError(
                "redis.asyncio is not installed. Add 'redis>=5' to your dependencies."
            )
        self._client = redis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )

    def _key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{self.namespace}:{digest}"

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        created = await self._client.set(
            self._key(key),
            "1",
            ex=ttl_seconds,
            nx=True,
        )
        return bool(created)
