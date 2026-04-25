from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from urllib.parse import urlparse

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .ai.ollama_runtime import OllamaRuntimeService
from .api.router import api_router
from .core.config import settings
from .core.csrf import validate_csrf_request
from .core.observability import (
    configure_sentry,
    install_metrics_route,
    observe_http_request,
)
from .db.repo.sync_job import SyncJobRepository
from .db.session import AsyncSessionLocal, dispose_db


def configure_logging() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL)
        ),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


configure_logging()
configure_sentry()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = OllamaRuntimeService()
    if settings.OLLAMA_BOOTSTRAP_MODE == "ensure":
        bootstrap_status = await runtime.ensure_models_ready()
    else:
        bootstrap_status = await runtime.check_readiness()
    app.state.ai_runtime_bootstrap = bootstrap_status
    if bootstrap_status.required and not bootstrap_status.ready:
        logger.warning(
            "Ollama bootstrap incomplete: %s",
            bootstrap_status.error or ", ".join(bootstrap_status.missing_models),
        )
    elif bootstrap_status.required:
        logger.info(
            "Ollama bootstrap ready for models: %s",
            ", ".join(bootstrap_status.required_models.values()),
        )

    try:
        async with AsyncSessionLocal() as session:
            reset = await SyncJobRepository(session).reset_stale_running_jobs(
                message="Job interrupted by API restart"
            )
        if reset:
            logger.warning("Reset %d zombie running sync jobs at startup", reset)
    except Exception:
        logger.exception("Failed to reset zombie sync jobs at startup")

    try:
        yield
    finally:
        await dispose_db()


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)


def _origin_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https":
        port = parsed.port or 443
    else:
        port = parsed.port or 80
    return host, port


def _request_host_port(request: Request) -> tuple[str, int]:
    return _origin_host_port(str(request.base_url))


@app.get("/", response_model=None)
async def root(request: Request):
    """Redirect browser to the SPA when origins differ; avoids blank 404 on API root."""
    frontend = settings.frontend_redirect_url
    if _origin_host_port(frontend) != _request_host_port(request):
        return RedirectResponse(url=frontend, status_code=307)
    return JSONResponse(
        {
            "app": settings.APP_NAME,
            "health": "/health",
            "docs": "/docs",
            "openapi": f"{settings.API_V1_PREFIX}/openapi.json",
            "api_prefix": settings.API_V1_PREFIX,
            "note": "FRONTEND_URL matches this server; redirect skipped. "
            "Point FRONTEND_URL at the Vite UI (e.g. http://localhost:5173) for Nextcloud SSO landing.",
        }
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    return await observe_http_request(request, call_next)


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    csrf_error = validate_csrf_request(request)
    if csrf_error is not None:
        return JSONResponse(status_code=403, content={"detail": csrf_error})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_metrics_route(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
