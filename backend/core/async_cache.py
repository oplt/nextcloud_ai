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
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._hits = 0
        self._misses = 0
        self._fills = 0
        self._evictions = 0
        self._errors = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "fills": self._fills,
            "evictions": self._evictions,
            "errors": self._errors,
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
            self._evictions += 1

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
            for task in self._inflight.values():
                task.cancel()
            self._inflight.clear()
            return
        self._store.pop(key, None)
        task = self._inflight.pop(key, None)
        if task is not None:
            task.cancel()

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(factory())
            self._inflight[key] = task
            task.add_done_callback(lambda completed: self._finish_fill(key, completed))
        value = await asyncio.shield(task)
        self._finish_fill(key, task)
        return value

    def _finish_fill(self, key: str, task: asyncio.Task[Any]) -> None:
        if self._inflight.get(key) is not task:
            return
        self._inflight.pop(key, None)
        try:
            value = task.result()
        except (Exception, asyncio.CancelledError):
            self._errors += 1
            return
        self._fills += 1
        self.set(key, value)
