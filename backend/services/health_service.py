from __future__ import annotations

import asyncio
from dataclasses import dataclass

from kombu import Connection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.ollama_runtime import OllamaRuntimeService, OllamaRuntimeStatus
from backend.core.config import Settings, settings

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency guard
    redis = None


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
        return await OllamaRuntimeService(settings_obj=self.settings).check_readiness()
