from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

from kombu import Connection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.embedding_client import embedding_provider_health
from ..ai.ollama_runtime import OllamaRuntimeService, OllamaRuntimeStatus
from ..core.config import Settings, settings

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency guard
    redis = None

_AI_RUNTIME_CACHE_TTL_SECONDS = 30.0
_ai_runtime_cache_status: OllamaRuntimeStatus | None = None
_ai_runtime_cache_checked_at = 0.0
_ai_runtime_cache_lock: asyncio.Lock | None = None


def _get_ai_runtime_cache_lock() -> asyncio.Lock:
    global _ai_runtime_cache_lock
    if _ai_runtime_cache_lock is None:
        _ai_runtime_cache_lock = asyncio.Lock()
    return _ai_runtime_cache_lock


@dataclass(slots=True, frozen=True)
class DependencyStatus:
    ok: bool
    detail: str

    @classmethod
    def healthy(cls) -> "DependencyStatus":
        return cls(ok=True, detail="ok")

    @classmethod
    def unhealthy(cls, exc: Exception) -> "DependencyStatus":
        message = exc.__class__.__name__
        if str(exc):
            message = f"{message}: {exc}"
        return cls(ok=False, detail=f"error: {message}")


class HealthCheckService:
    def __init__(self, *, settings_obj: Settings | None = None) -> None:
        self.settings = settings_obj or settings

    async def check_database(self, session: AsyncSession) -> DependencyStatus:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:
            return DependencyStatus.unhealthy(exc)
        return DependencyStatus.healthy()

    async def check_redis(self) -> DependencyStatus:
        if redis is None:  # pragma: no cover - runtime guard
            return DependencyStatus(
                ok=False,
                detail="error: redis.asyncio is not installed",
            )

        client = redis.from_url(
            self.settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            await client.ping()
        except Exception as exc:
            return DependencyStatus.unhealthy(exc)
        finally:
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()

        return DependencyStatus.healthy()

    async def check_broker(self) -> DependencyStatus:
        return await asyncio.to_thread(self._check_broker_sync)

    def _check_broker_sync(self) -> DependencyStatus:
        try:
            with Connection(
                self.settings.effective_celery_broker_url,
                connect_timeout=5,
            ) as connection:
                connection.ensure_connection(max_retries=0)
        except Exception as exc:
            return DependencyStatus.unhealthy(exc)
        return DependencyStatus.healthy()

    async def check_ai_runtime(self) -> OllamaRuntimeStatus:
        global _ai_runtime_cache_status, _ai_runtime_cache_checked_at

        now = time.monotonic()
        if (
            _ai_runtime_cache_status is not None
            and now - _ai_runtime_cache_checked_at < _AI_RUNTIME_CACHE_TTL_SECONDS
        ):
            return _ai_runtime_cache_status

        lock = _get_ai_runtime_cache_lock()
        async with lock:
            now = time.monotonic()
            if (
                _ai_runtime_cache_status is not None
                and now - _ai_runtime_cache_checked_at < _AI_RUNTIME_CACHE_TTL_SECONDS
            ):
                return _ai_runtime_cache_status

            status = await OllamaRuntimeService(settings_obj=self.settings).check_readiness()
            _ai_runtime_cache_status = status
            _ai_runtime_cache_checked_at = now
            return status

    def check_embedding_provider(self) -> dict[str, object]:
        return embedding_provider_health()
