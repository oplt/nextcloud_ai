"""Phase 5 resource ownership: shared cache, usage ContextVar, no prod stub."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.ai.llm_client import LLMClientFactory, StubGroundedLLMClient
from backend.ai.ollama_llm_client import (
    LLMHTTPError,
    LLMValidationError,
    OllamaLLMClient,
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
from backend.core.security import AuthContext
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
    assert cache.stats["fills"] == 1


@pytest.mark.asyncio
async def test_async_ttl_cache_waiter_cancellation_does_not_cancel_fill() -> None:
    cache = AsyncTTLCache(ttl_seconds=30, max_entries=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def factory() -> str:
        started.set()
        await release.wait()
        return "value"

    cancelled_waiter = asyncio.create_task(cache.get_or_set("k", factory))
    await started.wait()
    surviving_waiter = asyncio.create_task(cache.get_or_set("k", factory))
    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter
    release.set()
    assert await surviving_waiter == "value"
    assert cache.get("k") == "value"

    cache.set("other", "next")
    assert cache.stats["evictions"] == 1


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


@pytest.mark.asyncio
async def test_ollama_malformed_json_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"{", request=request)

    client = OllamaLLMClient(model="test", base_url="http://ollama")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.max_retries = 3
    try:
        with pytest.raises(LLMValidationError):
            await client.generate("prompt")
    finally:
        await client.aclose()
    assert calls == 1


@pytest.mark.asyncio
async def test_ollama_http_400_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad request"}, request=request)

    client = OllamaLLMClient(model="test", base_url="http://ollama")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.max_retries = 3
    try:
        with pytest.raises(LLMHTTPError) as error:
            await client.generate("prompt")
    finally:
        await client.aclose()
    assert error.value.status_code == 400
    assert calls == 1


def test_overview_cache_is_bounded() -> None:
    ProductIntelligenceService.invalidate_overview_cache()
    payload = SimpleNamespace(model_copy=lambda deep=True: "x")
    for index in range(80):
        ProductIntelligenceService._store_overview_cache(
            f"k{index}",
            1e18,
            payload,  # type: ignore[arg-type]
        )
    assert (
        len(ProductIntelligenceService._overview_cache)
        <= ProductIntelligenceService._overview_cache_max_entries
    )


@pytest.mark.asyncio
async def test_overview_cache_never_caches_acl_scoped_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ProductIntelligenceService.invalidate_overview_cache()
    monkeypatch.setattr(settings, "PRODUCT_INTELLIGENCE_ENABLED", False)
    service = ProductIntelligenceService(AsyncMock())
    auth = AuthContext(
        user_id="user-1",
        auth_provider="nextcloud",
        groups=frozenset({"finance"}),
        is_superuser=False,
    )

    await service.build_overview(auth=auth)
    await service.build_overview(auth=auth)

    assert ProductIntelligenceService._overview_cache == {}


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
    bundle.llm_cache.get("missing")
    bundle.llm_cache.set("present", {"value": True})
    assert bundle.llm_cache.get("present") == {"value": True}

    from prometheus_client import generate_latest

    from backend.core.observability import refresh_ai_cache_metrics

    refresh_ai_cache_metrics()
    metrics = generate_latest().decode("utf-8")
    assert 'nextcloud_ai_cache{cache="llm_cache",role="api",stat="hits"} 1.0' in metrics
    assert (
        'nextcloud_ai_cache{cache="llm_cache",role="api",stat="misses"} 1.0' in metrics
    )
    await stop_ai_resources()
    assert get_ai_resources() is None
