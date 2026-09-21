"""Process-owned true-reranker lifecycle (preload, readiness, explicit fallback)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from ..core.config import Settings, settings

logger = logging.getLogger(__name__)

FallbackMode = Literal["heuristic", "fail"]


class RerankDependencyError(RuntimeError):
    """Raised when the true reranker cannot be provisioned."""


@dataclass(slots=True)
class RerankRuntimeStatus:
    enabled: bool
    ready: bool
    model: str
    fallback_mode: FallbackMode
    dependency_installed: bool
    preloaded: bool
    using_fallback: bool
    error: str | None = None

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.ready:
            return "ready"
        if self.using_fallback:
            return "degraded"
        return "not_ready"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "ready": self.ready,
            "model": self.model,
            "fallback_mode": self.fallback_mode,
            "dependency_installed": self.dependency_installed,
            "preloaded": self.preloaded,
            "using_fallback": self.using_fallback,
            "error": self.error,
        }


_lock = asyncio.Lock()
_status: RerankRuntimeStatus | None = None
_reranker = None


def _sentence_transformers_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


def _build_status(
    *,
    settings_obj: Settings,
    ready: bool,
    preloaded: bool,
    using_fallback: bool,
    error: str | None,
) -> RerankRuntimeStatus:
    enabled = bool(settings_obj.RAG_TRUE_RERANK_ENABLED)
    return RerankRuntimeStatus(
        enabled=enabled,
        ready=ready if enabled else True,
        model=settings_obj.RAG_TRUE_RERANK_MODEL,
        fallback_mode=settings_obj.RAG_TRUE_RERANK_FALLBACK,
        dependency_installed=_sentence_transformers_available(),
        preloaded=preloaded,
        using_fallback=using_fallback if enabled else False,
        error=error,
    )


def get_rerank_status() -> RerankRuntimeStatus:
    global _status
    if _status is None:
        _status = _build_status(
            settings_obj=settings,
            ready=not settings.RAG_TRUE_RERANK_ENABLED,
            preloaded=False,
            using_fallback=False,
            error=None,
        )
    return _status


def get_shared_reranker():
    """Return the process-owned CrossEncoderReranker, or None when falling back."""
    return _reranker


async def ensure_reranker_ready(
    *,
    settings_obj: Settings | None = None,
    force_reload: bool = False,
) -> RerankRuntimeStatus:
    """Preload the cross-encoder once per process. Never download on first query."""
    global _status, _reranker

    cfg = settings_obj or settings
    async with _lock:
        if (
            not force_reload
            and _status is not None
            and (
                (not cfg.RAG_TRUE_RERANK_ENABLED)
                or _status.ready
                or _status.using_fallback
            )
            and _reranker is not None
        ):
            return _status

        if not cfg.RAG_TRUE_RERANK_ENABLED:
            _reranker = None
            _status = _build_status(
                settings_obj=cfg,
                ready=True,
                preloaded=False,
                using_fallback=False,
                error=None,
            )
            return _status

        if not _sentence_transformers_available():
            error = (
                "sentence_transformers is not installed; install the "
                "'rerank' extra (pip/uv install '.[rerank]')"
            )
            return _apply_unavailable(cfg, error)

        try:
            reranker = await asyncio.to_thread(_load_reranker, cfg)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("True reranker preload failed")
            return _apply_unavailable(cfg, error)

        _reranker = reranker
        _status = _build_status(
            settings_obj=cfg,
            ready=True,
            preloaded=True,
            using_fallback=False,
            error=None,
        )
        logger.info(
            "True reranker ready model=%s fallback=%s",
            cfg.RAG_TRUE_RERANK_MODEL,
            cfg.RAG_TRUE_RERANK_FALLBACK,
        )
        return _status


def _load_reranker(cfg: Settings):
    from .cross_encoder_reranker import CrossEncoderReranker

    return CrossEncoderReranker(model_name=cfg.RAG_TRUE_RERANK_MODEL)


def _apply_unavailable(cfg: Settings, error: str) -> RerankRuntimeStatus:
    global _status, _reranker
    _reranker = None
    fallback = cfg.RAG_TRUE_RERANK_FALLBACK
    if fallback == "fail":
        _status = _build_status(
            settings_obj=cfg,
            ready=False,
            preloaded=False,
            using_fallback=False,
            error=error,
        )
        if cfg.RAG_TRUE_RERANK_FAIL_STARTUP:
            raise RerankDependencyError(error)
        logger.error("True reranker unavailable (fail mode): %s", error)
        return _status

    _status = _build_status(
        settings_obj=cfg,
        ready=False,
        preloaded=False,
        using_fallback=True,
        error=error,
    )
    logger.warning(
        "True reranker unavailable; using explicit heuristic fallback: %s",
        error,
    )
    return _status


def reset_rerank_runtime_for_tests() -> None:
    """Test helper to clear process-global reranker state."""
    global _status, _reranker
    _status = None
    _reranker = None
