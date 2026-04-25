from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine_pid: int | None = None


def _build_engine() -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.SQL_ECHO,
        pool_pre_ping=settings.SQL_POOL_PRE_PING,
        pool_size=settings.SQL_POOL_SIZE,
        max_overflow=settings.SQL_MAX_OVERFLOW,
    )


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory, _engine_pid

    current_pid = os.getpid()
    if _session_factory is not None and _engine is not None and _engine_pid == current_pid:
        return _session_factory

    _engine = _build_engine()
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    _engine_pid = current_pid
    return _session_factory


def AsyncSessionLocal() -> AsyncSession:
    return _ensure_session_factory()()


def get_engine() -> AsyncEngine:
    _ensure_session_factory()
    assert _engine is not None
    return _engine


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_models() -> None:
    from .models import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine, _session_factory, _engine_pid

    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _engine_pid = None
