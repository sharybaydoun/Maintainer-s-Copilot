"""SQLAlchemy engine helpers — sync for app code, async for fastapi-users."""

from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def get_async_database_url() -> str | None:
    url = get_database_url()
    if not url:
        return None
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# ---------------------------------------------------------------- sync (app)


def get_engine() -> Engine | None:
    global _engine, _SessionLocal
    url = get_database_url()
    if not url:
        return None
    if _engine is None:
        _engine = create_engine(url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session() -> Session | None:
    if get_engine() is None or _SessionLocal is None:
        return None
    return _SessionLocal()


# ---------------------------------------------------------------- async (auth)


def get_async_engine() -> AsyncEngine | None:
    global _async_engine, _AsyncSessionLocal
    url = get_async_database_url()
    if not url:
        return None
    if _async_engine is None:
        _async_engine = create_async_engine(url, pool_pre_ping=True)
        _AsyncSessionLocal = async_sessionmaker(
            _async_engine, expire_on_commit=False, class_=AsyncSession
        )
    return _async_engine


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession. Used by fastapi-users."""
    if get_async_engine() is None or _AsyncSessionLocal is None:
        raise RuntimeError("Async database is not configured (DATABASE_URL missing)")
    async with _AsyncSessionLocal() as session:
        yield session
