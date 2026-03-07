from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import api_router
from backend.core.config import settings
from backend.db.session import dispose_db


def configure_logging() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.LOG_LEVEL)),
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()],
    )


configure_logging()
app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await dispose_db()
