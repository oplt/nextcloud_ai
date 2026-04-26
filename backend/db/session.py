from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import settings

T = TypeVar("T")

_process_engines: dict[int, tuple[AsyncEngine, async_sessionmaker[AsyncSession]]] = {}


def run_async_safe(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run an async coroutine from sync code.

    Do not call this from an already-running event loop. Blocking the same loop
    deadlocks. Async callers must await directly.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    raise RuntimeError("run_async_safe() was called from an async context; await the coroutine instead.")


def _get_engine_key() -> int:
    return os.getpid()


def _build_engine() -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.SQL_ECHO,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=settings.SQL_POOL_SIZE,
        max_overflow=settings.SQL_MAX_OVERFLOW,
        pool_use_lifo=True,
        pool_timeout=30,
        connect_args={
            "server_settings": {
                "application_name": f"nextcloud_ai_{os.getpid()}",
            },
            "timeout": 30,
            "command_timeout": 120,
        },
    )


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    pid = _get_engine_key()

    if pid not in _process_engines:
        engine = _build_engine()
        _process_engines[pid] = (
            engine,
            async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            ),
        )

    return _process_engines[pid][1]


def AsyncSessionLocal() -> AsyncSession:
    return _get_session_factory()()


def get_engine() -> AsyncEngine:
    pid = _get_engine_key()
    if pid not in _process_engines:
        _get_session_factory()
    return _process_engines[pid][0]


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    from .models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    pid = _get_engine_key()
    item = _process_engines.pop(pid, None)
    if item is None:
        return

    engine, _ = item
    await engine.dispose()