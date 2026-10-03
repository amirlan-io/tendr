"""Healthcheck и базовые эндпоинты."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.llm import get_llm

router = APIRouter(tags=["health"])


async def _db_ping() -> None:
    from sqlalchemy import text

    from app.db import engine

    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


def _qdrant_is_available() -> bool:
    from app.rag.store import _get_shared_qdrant_client

    client = _get_shared_qdrant_client()
    if client is None:
        return False
    try:
        client.get_collections()
        return True
    except Exception:
        return False


async def _embed_ok(llm) -> bool:
    """Запасная проверка эмбеддингов для провайдеров без метода."""
    try:
        await llm.embed("ping")
        return True
    except Exception:
        return False


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    checks: dict[str, str] = {}
    status = "ok"

    try:
        await _db_ping()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "db unavailable"
        status = "degraded"

    try:
        qdrant_ok = await asyncio.wait_for(
            asyncio.to_thread(_qdrant_is_available),
            timeout=3.0,
        )
    except Exception:
        qdrant_ok = False

    if qdrant_ok:
        checks["qdrant"] = "ok"
    else:
        checks["qdrant"] = "qdrant unavailable"
        status = "degraded"

    llm = get_llm()
    try:
        llm_ok = await asyncio.wait_for(llm.healthcheck(), timeout=15.0)
        checks["llm"] = "ok" if llm_ok else "llm unavailable"
        if not llm_ok:
            status = "degraded"
    except Exception:
        checks["llm"] = "llm unavailable"
        status = "degraded"

    # Эмбеддинги нужны только для RAG. Их отсутствие не ломает анализ
    # лотов, поэтому показываем отдельно и НЕ роняем статус: иначе
    # провайдер без embed-поддержки всегда выглядит как авария.
    try:
        embeddings_ok = await asyncio.wait_for(
            getattr(llm, "supports_embeddings", lambda: _embed_ok(llm))(),
            timeout=10.0,
        )
        checks["embeddings"] = "ok" if embeddings_ok else "not supported by provider"
    except Exception:
        checks["embeddings"] = "not supported by provider"

    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "llm_provider": settings.llm_provider,
        "checks": checks,
    }


@router.get("/health/llm")
async def health_llm() -> dict:
    llm = get_llm()
    ok = await llm.healthcheck()
    return {"provider": llm.name, "ok": ok}
