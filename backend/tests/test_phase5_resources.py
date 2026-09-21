"""Phase 5 resource ownership: shared cache, usage ContextVar, no prod stub."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.ai.llm_client import LLMClientFactory, StubGroundedLLMClient
from backend.ai.ollama_llm_client import (
    consume_generation_usage,
    peek_generation_usage,
)
from backend.core.async_cache import AsyncTTLCache
from backend.core.ai_resources import (
    get_ai_resources,
    start_ai_resources,
    stop_ai_resources,
)
from backend.core.config import settings
from backend.services.product_intelligence_service import ProductIntelligenceService


@pytest.mark.asyncio
async def test_async_ttl_cache_single_flight() -> None:
    cache = AsyncTTLCache(ttl_seconds=30, max_entries=8)
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "value"

    first, second = await asyncio.gather(
        cache.get_or_set("k", factory),
        cache.get_or_set("k", factory),
    )
    assert first == second == "value"
    assert calls == 1
    assert cache.get("k") == "value"


@pytest.mark.asyncio
async def test_generation_usage_is_task_local() -> None:
    async def writer(value: str) -> str | None:
        from backend.ai.ollama_llm_client import _generation_usage

        _generation_usage.set({"token": value})
        await asyncio.sleep(0.01)
        return peek_generation_usage()

    a, b = await asyncio.gather(writer("a"), writer("b"))
    assert a == {"token": "a"}
    assert b == {"token": "b"}
    # Parent context unchanged.
    assert consume_generation_usage() is None


def test_production_disables_stub_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "stub")
    # Bypass cached_property by deleting if present.
    settings.__dict__.pop("effective_llm_provider", None)
    client = LLMClientFactory.create(reuse_process=False)
    assert not isinstance(client, StubGroundedLLMClient)
    # Resilient without fallback.
    assert getattr(client, "fallback", None) is None


def test_overview_cache_is_bounded() -> None:
    ProductIntelligenceService.invalidate_overview_cache()
    payload = SimpleNamespace(model_copy=lambda deep=True: "x")
    for index in range(80):
        ProductIntelligenceService._store_overview_cache(
            f"k{index}", 1e18, payload  # type: ignore[arg-type]
        )
    assert (
        len(ProductIntelligenceService._overview_cache)
        <= ProductIntelligenceService._overview_cache_max_entries
    )


@pytest.mark.asyncio
async def test_ai_resources_start_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    await stop_ai_resources()
    monkeypatch.setattr(settings, "RAG_TRUE_RERANK_PRELOAD", False)
    monkeypatch.setattr(settings, "RAG_TRUE_RERANK_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "stub")
    settings.__dict__.pop("effective_llm_provider", None)
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "deterministic")
    settings.__dict__.pop("effective_embedding_provider", None)

    bundle = await start_ai_resources(role="api")
    assert get_ai_resources() is bundle
    assert bundle.llm_client is not None
    await stop_ai_resources()
    assert get_ai_resources() is None
