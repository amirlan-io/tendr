"""Healthcheck и базовые эндпоинты."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.llm import get_llm

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "llm_provider": settings.llm_provider,
    }


@router.get("/health/llm")
async def health_llm() -> dict:
    llm = get_llm()
    ok = await llm.healthcheck()
    return {"provider": llm.name, "ok": ok}
