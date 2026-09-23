"""Process-owned AI resource lifecycle (API worker and Celery worker).

Owns shared HTTP clients, bounded caches, and optional heavy models for the
current process. Call ``start_ai_resources`` once at process boot and
``stop_ai_resources`` on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from .async_cache import AsyncTTLCache
from .config import settings

logger = logging.getLogger(__name__)

ProcessRole = Literal["api", "worker"]


@dataclass
class AIResourceBundle:
    role: ProcessRole
    llm_cache: AsyncTTLCache
    llm_client: Any | None = None
    embedding_client: Any | None = None
    started_at: float = field(default_factory=time.monotonic)

    def cache_stats(self) -> dict[str, object]:
        return {
            "role": self.role,
            "llm_cache": self.llm_cache.stats,
            "uptime_seconds": round(time.monotonic() - self.started_at, 3),
        }


_bundle: AIResourceBundle | None = None
_lock = asyncio.Lock()


def get_ai_resources() -> AIResourceBundle | None:
    return _bundle


async def start_ai_resources(*, role: ProcessRole) -> AIResourceBundle:
    """Idempotent process boot for shared AI clients and caches."""
    global _bundle
    async with _lock:
        if _bundle is not None:
            return _bundle

        llm_cache = AsyncTTLCache(
            ttl_seconds=settings.LLM_CACHE_TTL_SECONDS,
            max_entries=settings.LLM_CACHE_MAX_ENTRIES,
        )
        bundle = AIResourceBundle(role=role, llm_cache=llm_cache)

        from ..ai.embedding_client import EmbeddingClientFactory
        from ..ai.llm_client import LLMClientFactory

        try:
            bundle.embedding_client = EmbeddingClientFactory.create(
                allow_deterministic=settings.APP_ENV in {"development", "test"},
                reuse_process=False,
            )
        except Exception:
            logger.exception("Embedding client init failed role=%s", role)
            bundle.embedding_client = None

        bundle.llm_client = LLMClientFactory.create(
            shared_cache=llm_cache, reuse_process=False
        )

        if role == "api" and settings.RAG_TRUE_RERANK_PRELOAD:
            from ..rag.rerank_runtime import ensure_reranker_ready

            try:
                await ensure_reranker_ready()
            except Exception:
                logger.exception("Reranker preload during AI resource start failed")
        elif role == "worker" and settings.RAG_TRUE_RERANK_ENABLED:
            # Workers that rank should also own one model copy.
            from ..rag.rerank_runtime import ensure_reranker_ready

            try:
                await ensure_reranker_ready()
            except Exception:
                logger.exception("Worker reranker preload failed")

        _bundle = bundle
        logger.info("AI resources started role=%s", role)
        return bundle


async def stop_ai_resources() -> None:
    global _bundle
    async with _lock:
        bundle = _bundle
        _bundle = None
    if bundle is None:
        return
    for client in (bundle.llm_client, bundle.embedding_client):
        close = getattr(client, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception:
                logger.exception("AI resource close failed")
    bundle.llm_cache.invalidate()
    from ..rag.rerank_runtime import reset_rerank_runtime_for_tests

    # Clear process-owned reranker reference on shutdown (not only tests).
    reset_rerank_runtime_for_tests()
    logger.info("AI resources stopped role=%s", bundle.role)
