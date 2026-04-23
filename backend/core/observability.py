from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from backend.core.config import settings

try:  # pragma: no cover - optional runtime integration
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
except Exception:  # pragma: no cover - dependency guard
    sentry_sdk = None
    CeleryIntegration = None
    FastApiIntegration = None


logger = logging.getLogger(__name__)

REQUEST_ID_CTX: ContextVar[str | None] = ContextVar("request_id", default=None)
TRACE_ID_CTX: ContextVar[str | None] = ContextVar("trace_id", default=None)

HTTP_REQUESTS_TOTAL = Counter(
    "nextcloud_ai_http_requests_total",
    "Total HTTP requests served by the API.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "nextcloud_ai_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "route"],
)
SYNC_JOB_TRANSITIONS_TOTAL = Counter(
    "nextcloud_ai_sync_job_transitions_total",
    "Sync job state transitions.",
    ["job_type", "status"],
)

RAG_EMBEDDING_SECONDS = Histogram(
    "nextcloud_ai_rag_embedding_seconds",
    "Time to produce the query embedding for retrieval.",
    ["provider", "outcome"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)
RAG_RETRIEVAL_SOURCES_RETURNED = Histogram(
    "nextcloud_ai_rag_retrieval_sources_returned",
    "Number of grounded sources returned after retrieval (before rerank).",
    buckets=(0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, float("inf")),
)
RAG_GRAPH_EXPAND_EVENTS_TOTAL = Counter(
    "nextcloud_ai_rag_graph_expand_events_total",
    "Knowledge-graph document expansion attempts during retrieval.",
    ["phase", "applied"],
)
RAG_RERANK_EVENTS_TOTAL = Counter(
    "nextcloud_ai_rag_rerank_events_total",
    "Rerank/compress pass applied before grounding.",
    ["order_changed", "content_truncated"],
)
RAG_CITATION_FILTER_EVENTS_TOTAL = Counter(
    "nextcloud_ai_rag_citation_filter_events_total",
    "Citation filtering relative to reranked candidate sources.",
    ["outcome"],
)
RAG_VERIFICATION_DECISIONS_TOTAL = Counter(
    "nextcloud_ai_rag_verification_decisions_total",
    "Answer verification outcomes for grounded chat turns.",
    ["result", "shadow_mode"],
)
RAG_VERIFICATION_SHADOW_OVERRIDES_TOTAL = Counter(
    "nextcloud_ai_rag_verification_shadow_overrides_total",
    "Shadow mode kept model output despite failed verification.",
    ["reason"],
)
RAG_STAGE_ERRORS_TOTAL = Counter(
    "nextcloud_ai_rag_stage_errors_total",
    "RAG pipeline stage failures (chat ask path).",
    ["stage"],
)
RAG_CHAT_LOW_CONFIDENCE_TOTAL = Counter(
    "nextcloud_ai_rag_chat_low_confidence_answers_total",
    "Assistant answers persisted with low answer_confidence.",
    ["below"],
)
INTELLIGENCE_EXTRACTION_FAILURES_TOTAL = Counter(
    "nextcloud_ai_intelligence_extraction_failures_total",
    "Product intelligence extraction failed after indexing.",
)


def configure_sentry() -> None:
    if not settings.SENTRY_DSN or sentry_sdk is None:
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[
            integration
            for integration in [
                FastApiIntegration() if FastApiIntegration is not None else None,
                CeleryIntegration() if CeleryIntegration is not None else None,
            ]
            if integration is not None
        ],
        environment=settings.APP_ENV,
        send_default_pii=False,
    )


def install_metrics_route(app: FastAPI) -> None:
    if not settings.METRICS_ENABLED:
        return

    @app.get(settings.METRICS_PATH, include_in_schema=False)
    async def metrics() -> Response:
        return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


def get_request_id() -> str | None:
    return REQUEST_ID_CTX.get()


def get_trace_id() -> str | None:
    return TRACE_ID_CTX.get()


def record_job_transition(*, job_type: str, status: str) -> None:
    SYNC_JOB_TRANSITIONS_TOTAL.labels(job_type=job_type, status=status).inc()


def _embedding_provider_label() -> str:
    return str(settings.effective_embedding_provider)


def record_rag_embedding_latency(*, seconds: float, outcome: str) -> None:
    if not settings.METRICS_ENABLED:
        return
    RAG_EMBEDDING_SECONDS.labels(
        provider=_embedding_provider_label(),
        outcome=outcome,
    ).observe(max(0.0, float(seconds)))


def record_rag_retrieval_delivery(
    *, source_count: int, retrieval_debug: dict[str, object] | None
) -> None:
    if not settings.METRICS_ENABLED:
        return
    RAG_RETRIEVAL_SOURCES_RETURNED.observe(float(source_count))
    dbg = retrieval_debug or {}
    for phase, key in (
        ("preferred", "graph_expansion_preferred"),
        ("broad", "graph_expansion_broad"),
    ):
        block = dbg.get(key)
        if not isinstance(block, dict):
            continue
        applied = "true" if block.get("applied") else "false"
        RAG_GRAPH_EXPAND_EVENTS_TOTAL.labels(phase=phase, applied=applied).inc()


def record_rag_rerank_event(*, order_changed: bool, content_truncated_count: int) -> None:
    if not settings.METRICS_ENABLED:
        return
    RAG_RERANK_EVENTS_TOTAL.labels(
        order_changed="true" if order_changed else "false",
        content_truncated="true" if content_truncated_count > 0 else "false",
    ).inc()


def record_rag_citation_filter(*, before_count: int, after_count: int) -> None:
    if not settings.METRICS_ENABLED:
        return
    if after_count == 0 and before_count > 0:
        outcome = "all_dropped"
    elif after_count < before_count:
        outcome = "reduced"
    elif before_count == 0:
        outcome = "no_candidates"
    else:
        outcome = "unchanged"
    RAG_CITATION_FILTER_EVENTS_TOTAL.labels(outcome=outcome).inc()


def record_rag_verification(*, result: str | None, shadow_mode: bool) -> None:
    if not settings.METRICS_ENABLED:
        return
    RAG_VERIFICATION_DECISIONS_TOTAL.labels(
        result=result or "unknown",
        shadow_mode="true" if shadow_mode else "false",
    ).inc()


def record_rag_shadow_override(*, reason: str) -> None:
    if not settings.METRICS_ENABLED:
        return
    RAG_VERIFICATION_SHADOW_OVERRIDES_TOTAL.labels(reason=reason).inc()


def record_rag_stage_error(*, stage: str) -> None:
    if not settings.METRICS_ENABLED:
        return
    RAG_STAGE_ERRORS_TOTAL.labels(stage=stage).inc()


def record_rag_low_confidence_answer(
    *, confidence: float | None, threshold: float = 0.35
) -> None:
    if not settings.METRICS_ENABLED or confidence is None:
        return
    if confidence < threshold:
        RAG_CHAT_LOW_CONFIDENCE_TOTAL.labels(below=str(round(threshold, 2))).inc()


def record_intelligence_extraction_failure() -> None:
    if not settings.METRICS_ENABLED:
        return
    INTELLIGENCE_EXTRACTION_FAILURES_TOTAL.inc()


def _extract_route_pattern(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


def _extract_trace_id(request: Request, request_id: str) -> str:
    traceparent = request.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 4 and parts[1]:
            return parts[1]

    trace_header = request.headers.get(settings.TRACE_ID_HEADER_NAME)
    if trace_header:
        return trace_header
    return request_id


async def observe_http_request(
    request: Request,
    call_next: Callable,
) -> Response:
    request_id = request.headers.get(settings.REQUEST_ID_HEADER_NAME) or str(uuid.uuid4())
    trace_id = _extract_trace_id(request, request_id)
    request.state.request_id = request_id
    request.state.trace_id = trace_id

    request_token = REQUEST_ID_CTX.set(request_id)
    trace_token = TRACE_ID_CTX.set(trace_id)
    started_at = time.perf_counter()
    route = _extract_route_pattern(request)
    response: Response | None = None
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - started_at
        if settings.METRICS_ENABLED:
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                route=route,
                status=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
                route=route,
            ).observe(elapsed)

        if response is not None:
            response.headers.setdefault(settings.REQUEST_ID_HEADER_NAME, request_id)
            response.headers.setdefault(settings.TRACE_ID_HEADER_NAME, trace_id)

        logger.info(
            "request.completed",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "method": request.method,
                "route": route,
                "status_code": status_code,
                "duration_ms": round(elapsed * 1000, 2),
            },
        )
        REQUEST_ID_CTX.reset(request_token)
        TRACE_ID_CTX.reset(trace_token)
