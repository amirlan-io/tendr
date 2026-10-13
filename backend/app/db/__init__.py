"""Database setup: engine, session factory, base class."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_pool_options = {} if _settings.database_url.startswith("sqlite") else {"pool_size": 5, "max_overflow": 10}
engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    **_pool_options,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager для коротких сессий (внутри хендлеров)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependency для FastAPI."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Создать все таблицы (используется для dev). В проде — Alembic."""
    from app.db import models  # noqa: F401  (регистрация моделей)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
