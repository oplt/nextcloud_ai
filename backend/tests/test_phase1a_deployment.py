"""Phase 1A acceptance: deployment import smoke, rerank modes, bridge package."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.config import Settings
from backend.rag.rerank_runtime import (
    ensure_reranker_ready,
    get_rerank_status,
    get_shared_reranker,
    reset_rerank_runtime_for_tests,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_ROOT = REPO_ROOT / "nc_ai_bridge"


def test_backend_entrypoint_imports() -> None:
    import backend.main as main_mod
    import backend.workers.celery_app as celery_mod
    import backend.scripts.seed_admin as seed_mod

    assert main_mod.app is not None
    assert celery_mod.celery_app is not None
    assert callable(seed_mod.main)


@pytest.mark.asyncio
async def test_rerank_disabled_mode_is_ready_without_model() -> None:
    reset_rerank_runtime_for_tests()
    cfg = Settings(
        RAG_TRUE_RERANK_ENABLED=False,
        RAG_TRUE_RERANK_PRELOAD=False,
        APP_ENV="test",
    )
    status = await ensure_reranker_ready(settings_obj=cfg)
    assert status.enabled is False
    assert status.ready is True
    assert status.status == "disabled"
    assert get_shared_reranker() is None


@pytest.mark.asyncio
async def test_rerank_enabled_missing_dep_uses_explicit_heuristic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rerank_runtime_for_tests()
    monkeypatch.setattr(
        "backend.rag.rerank_runtime._sentence_transformers_available",
        lambda: False,
    )
    cfg = Settings(
        RAG_TRUE_RERANK_ENABLED=True,
        RAG_TRUE_RERANK_FALLBACK="heuristic",
        RAG_TRUE_RERANK_FAIL_STARTUP=False,
        APP_ENV="test",
    )
    status = await ensure_reranker_ready(settings_obj=cfg)
    assert status.enabled is True
    assert status.ready is False
    assert status.using_fallback is True
    assert status.status == "degraded"
    assert get_shared_reranker() is None
    assert "sentence_transformers" in (status.error or "")


@pytest.mark.asyncio
async def test_rerank_enabled_preloads_shared_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rerank_runtime_for_tests()
    loaded_model = object()

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(
        "backend.rag.rerank_runtime._sentence_transformers_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "backend.rag.rerank_runtime._load_reranker",
        lambda _cfg: loaded_model,
    )
    monkeypatch.setattr(
        "backend.rag.rerank_runtime.asyncio.to_thread",
        run_inline,
    )
    cfg = Settings(
        RAG_TRUE_RERANK_ENABLED=True,
        RAG_TRUE_RERANK_FALLBACK="fail",
        RAG_TRUE_RERANK_FAIL_STARTUP=True,
        APP_ENV="test",
    )
    status = await ensure_reranker_ready(settings_obj=cfg)
    assert status.ready is True
    assert status.preloaded is True
    assert status.using_fallback is False
    assert get_shared_reranker() is loaded_model


@pytest.mark.asyncio
async def test_rerank_fail_mode_marks_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rerank_runtime_for_tests()
    monkeypatch.setattr(
        "backend.rag.rerank_runtime._sentence_transformers_available",
        lambda: False,
    )
    cfg = Settings(
        RAG_TRUE_RERANK_ENABLED=True,
        RAG_TRUE_RERANK_FALLBACK="fail",
        RAG_TRUE_RERANK_FAIL_STARTUP=False,
        APP_ENV="test",
    )
    status = await ensure_reranker_ready(settings_obj=cfg)
    assert status.status == "not_ready"
    assert status.using_fallback is False


def test_health_payload_includes_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.health_service import HealthCheckService

    reset_rerank_runtime_for_tests()
    status = get_rerank_status()
    assert "enabled" in status.to_dict()
    service = HealthCheckService()
    payload = service.check_rerank_runtime().to_dict()
    assert payload["status"] in {"disabled", "ready", "degraded", "not_ready"}


def test_bridge_lib_package_complete() -> None:
    required = [
        BRIDGE_ROOT / "composer.json",
        BRIDGE_ROOT / "appinfo" / "routes.php",
        BRIDGE_ROOT / "lib" / "AppInfo" / "Application.php",
        BRIDGE_ROOT / "lib" / "Controller" / "AuthController.php",
        BRIDGE_ROOT / "lib" / "Controller" / "PageController.php",
    ]
    missing = [
        str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()
    ]
    assert missing == [], f"bridge package incomplete: {missing}"

    routes = (BRIDGE_ROOT / "appinfo" / "routes.php").read_text(encoding="utf-8")
    assert "auth#bootstrap" in routes
    assert "page#index" in routes

    auth = (BRIDGE_ROOT / "lib" / "Controller" / "AuthController.php").read_text(
        encoding="utf-8"
    )
    assert "bridge_token" in auth
    assert "HS256" in auth or "hash_hmac" in auth
    assert "preferred_username" in auth
    assert "nc_base_url" in auth
    assert "IURLGenerator" in auth
    assert "getAbsoluteURL" in auth
    assert "x-forwarded-host" not in auth.lower()
    assert "NoCSRFRequired" not in auth


def test_vector_extension_in_baseline_and_forward_migration() -> None:
    versions = REPO_ROOT / "backend" / "alembic" / "versions"
    baseline = (versions / "00c7539a7dcd_generate_tables.py").read_text(
        encoding="utf-8"
    )
    forward = (versions / "a1b2c3d4e5f6_ensure_vector_extension.py").read_text(
        encoding="utf-8"
    )
    assert "CREATE EXTENSION IF NOT EXISTS vector" in baseline
    assert "CREATE EXTENSION IF NOT EXISTS vector" in forward
    assert 'down_revision: Union[str, Sequence[str], None] = "4b7f9d2fd6d1"' in forward


def test_compose_uses_fully_qualified_backend_modules() -> None:
    deploy = (REPO_ROOT / "deployment" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "uvicorn backend.main:app" in deploy
    assert "python -m backend.scripts.seed_admin" in deploy
    assert "celery -A backend.workers.celery_app:celery_app" in deploy
    assert "PYTHONPATH: /app" in deploy
    assert "working_dir: /app" in deploy
    # Legacy broken forms must stay gone.
    assert "uvicorn main:app" not in deploy
    assert "python -m scripts.seed_admin" not in deploy
    assert "celery -A workers.celery_app" not in deploy


def test_enabled_reranker_is_preprovisioned_for_docker_and_local_setup() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    local_makefile = (REPO_ROOT / "Makefile.local").read_text(encoding="utf-8")
    assert "ARG BUILD_RERANK_MODEL=1" in dockerfile
    assert "ENV HF_HUB_OFFLINE=1" in dockerfile
    assert "python -m backend.scripts.provision_rerank_model" in local_makefile


def test_compose_bounds_shared_ollama_capacity() -> None:
    compose = (REPO_ROOT / "deployment" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "OLLAMA_NUM_PARALLEL" in compose
    assert "OLLAMA_MAX_LOADED_MODELS" in compose
    assert "OLLAMA_MAX_QUEUE" in compose
