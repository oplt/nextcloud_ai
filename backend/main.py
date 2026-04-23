from __future__ import annotations

from contextlib import asynccontextmanager
import logging

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.ai.ollama_runtime import OllamaRuntimeService
from backend.api.router import api_router
from backend.core.config import settings
from backend.core.csrf import validate_csrf_request
from backend.core.observability import (
    configure_sentry,
    install_metrics_route,
    observe_http_request,
)
from backend.db.session import dispose_db


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
    bootstrap_status = await OllamaRuntimeService().ensure_models_ready()
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
        yield
    finally:
        await dispose_db()


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)


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
    allow_origins=settings.frontend_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_metrics_route(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
