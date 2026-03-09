from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from backend.ai.ollama_runtime import OllamaRuntimeStatus
from backend.db.session import get_db_session
from backend.main import app
from backend.services.health_service import DependencyStatus


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


def ready_ai_status() -> OllamaRuntimeStatus:
    return OllamaRuntimeStatus(
        required=True,
        ready=True,
        providers={"embedding": "ollama", "llm": "ollama"},
        base_url="http://ollama:11434",
        required_models={
            "embedding": "bge-m3:latest",
            "chat": "llama3:latest",
        },
        available_models=["bge-m3:latest", "llama3:latest"],
    )


async def dependency_status(status: DependencyStatus) -> DependencyStatus:
    return status


async def ai_runtime_status(status: OllamaRuntimeStatus) -> OllamaRuntimeStatus:
    return status


def test_health_ready_returns_200_when_all_dependencies_are_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.main.OllamaRuntimeService.ensure_models_ready",
        fake_startup_bootstrap,
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_redis",
        lambda _self: dependency_status(DependencyStatus.healthy()),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_broker",
        lambda _self: dependency_status(DependencyStatus.healthy()),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_ai_runtime",
        lambda _self: ai_runtime_status(ready_ai_status()),
    )
    app.dependency_overrides[get_db_session] = override_db_session

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "redis": "ok",
        "broker": "ok",
        "ai_runtime": ready_ai_status().to_dict(),
    }


def test_health_ready_returns_503_when_redis_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.main.OllamaRuntimeService.ensure_models_ready",
        fake_startup_bootstrap,
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_redis",
        lambda _self: dependency_status(
            DependencyStatus(
                ok=False,
                detail="error: ConnectionError: Redis unavailable",
            )
        ),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_broker",
        lambda _self: dependency_status(DependencyStatus.healthy()),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_ai_runtime",
        lambda _self: ai_runtime_status(ready_ai_status()),
    )
    app.dependency_overrides[get_db_session] = override_db_session

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["redis"] == "error: ConnectionError: Redis unavailable"


def test_health_ready_returns_503_when_broker_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.main.OllamaRuntimeService.ensure_models_ready",
        fake_startup_bootstrap,
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_redis",
        lambda _self: dependency_status(DependencyStatus.healthy()),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_broker",
        lambda _self: dependency_status(
            DependencyStatus(
                ok=False,
                detail="error: OperationalError: Broker unavailable",
            )
        ),
    )
    monkeypatch.setattr(
        "backend.services.health_service.HealthCheckService.check_ai_runtime",
        lambda _self: ai_runtime_status(ready_ai_status()),
    )
    app.dependency_overrides[get_db_session] = override_db_session

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["broker"] == "error: OperationalError: Broker unavailable"
