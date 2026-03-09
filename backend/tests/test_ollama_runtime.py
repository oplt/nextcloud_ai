from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.ai.ollama_runtime import OllamaRuntimeService, OllamaRuntimeStatus
from backend.core.config import Settings
from backend.db.session import get_db_session
from backend.main import app
from backend.services.health_service import DependencyStatus


COMMON_SETTINGS = {
    "_env_file": None,
    "DATABASE_URL": "postgresql+asyncpg://nextcloud:secret@localhost:5432/nextcloud",
    "EMBEDDING_DIM": 1024,
    "APP_ENV": "production",
    "OLLAMA_BASE_URL": "http://ollama:11434",
}


@pytest.mark.asyncio
async def test_ensure_models_ready_pulls_missing_models_and_warms_them() -> None:
    pulled_models: list[str] = []
    warm_calls: list[str] = []
    available_models: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": model} for model in sorted(available_models)]},
            )

        payload = json.loads(request.content.decode("utf-8"))
        if request.url.path == "/api/pull":
            model = payload["model"]
            pulled_models.append(model)
            available_models.add(model)
            return httpx.Response(200, json={"status": "success"})
        if request.url.path == "/api/embeddings":
            warm_calls.append("embedding")
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        if request.url.path == "/api/generate":
            warm_calls.append("chat")
            return httpx.Response(200, json={"response": "READY"})

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(**COMMON_SETTINGS)
    runtime = OllamaRuntimeService(
        settings_obj=settings,
        transport=httpx.MockTransport(handler),
    )

    status = await runtime.ensure_models_ready()

    assert status.ready is True
    assert status.missing_models == []
    assert pulled_models == [
        settings.OLLAMA_EMBEDDING_MODEL,
        settings.OLLAMA_CHAT_MODEL,
    ]
    assert warm_calls == ["embedding", "chat"]
    assert status.warmed_capabilities == ["embedding", "chat"]
    assert status.available_models == sorted(
        [settings.OLLAMA_CHAT_MODEL, settings.OLLAMA_EMBEDDING_MODEL]
    )


@pytest.mark.asyncio
async def test_check_readiness_fails_when_required_models_are_missing() -> None:
    settings = Settings(**COMMON_SETTINGS)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": settings.OLLAMA_CHAT_MODEL}]})

    runtime = OllamaRuntimeService(
        settings_obj=settings,
        transport=httpx.MockTransport(handler),
    )

    status = await runtime.check_readiness()

    assert status.ready is False
    assert status.missing_models == [settings.OLLAMA_EMBEDDING_MODEL]
    assert "Missing required Ollama models" in (status.error or "")


@pytest.mark.asyncio
async def test_ensure_models_ready_warms_models_even_when_already_present() -> None:
    settings = Settings(**COMMON_SETTINGS)
    warm_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": settings.OLLAMA_EMBEDDING_MODEL},
                        {"name": settings.OLLAMA_CHAT_MODEL},
                    ]
                },
            )
        if request.url.path == "/api/embeddings":
            warm_calls.append("embedding")
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        if request.url.path == "/api/generate":
            warm_calls.append("chat")
            return httpx.Response(200, json={"response": "READY"})

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    runtime = OllamaRuntimeService(
        settings_obj=settings,
        transport=httpx.MockTransport(handler),
    )

    status = await runtime.ensure_models_ready()

    assert status.ready is True
    assert warm_calls == ["embedding", "chat"]
    assert status.warmed_capabilities == ["embedding", "chat"]


def test_health_ready_returns_503_when_ai_runtime_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        async def execute(self, _query) -> int:
            return 1

    async def override_db_session():
        yield FakeSession()

    async def fake_startup_bootstrap(self) -> OllamaRuntimeStatus:
        return OllamaRuntimeStatus(
            required=False,
            ready=True,
            providers={"embedding": "deterministic", "llm": "stub"},
            base_url="http://ollama:11434",
            required_models={},
        )

    async def fake_check_readiness(self) -> OllamaRuntimeStatus:
        return OllamaRuntimeStatus(
            required=True,
            ready=False,
            providers={"embedding": "ollama", "llm": "ollama"},
            base_url="http://ollama:11434",
            required_models={
                "embedding": "bge-m3:latest",
                "chat": "llama3:latest",
            },
            available_models=["bge-m3:latest"],
            missing_models=["llama3:latest"],
            error="Missing required Ollama models: llama3:latest",
        )

    monkeypatch.setattr(
        "backend.main.OllamaRuntimeService.ensure_models_ready",
        fake_startup_bootstrap,
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_redis",
        lambda _self: _async_dependency_status(DependencyStatus.healthy()),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_broker",
        lambda _self: _async_dependency_status(DependencyStatus.healthy()),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_ai_runtime",
        fake_check_readiness,
    )
    app.dependency_overrides[get_db_session] = override_db_session

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["ai_runtime"]["missing_models"] == ["llama3:latest"]


async def _async_dependency_status(status: DependencyStatus) -> DependencyStatus:
    return status
