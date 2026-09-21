"""Bounded async TTL/LRU cache with single-flight fills."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable


class AsyncTTLCache:
    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_entries = max(0, int(max_entries))
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "inflight": len(self._inflight),
        }

    def get(self, key: str) -> Any | None:
        if self.ttl_seconds <= 0 or self.max_entries <= 0:
            return None
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            self._store.pop(key, None)
            self._misses += 1
            return None
        self._store.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        if self.ttl_seconds <= 0 or self.max_entries <= 0:
            return
        self._store[key] = (time.monotonic() + self.ttl_seconds, value)
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
            return
        self._store.pop(key, None)

    async def get_or_set(
        self, key: str, factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        existing = self._inflight.get(key)
        if existing is not None:
            return await existing
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._inflight[key] = future
        try:
            value = await factory()
            self.set(key, value)
            future.set_result(value)
            return value
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)
