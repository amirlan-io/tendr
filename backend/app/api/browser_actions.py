"""
API endpoint для browser actions.
POST /api/browser/run — запуск задачи
GET /api/browser/status/{session_id} — статус
POST /api/browser/continue/{session_id} — продолжить HIL сессию
POST /api/browser/stop/{session_id} — остановить
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.browser_use import BrowserUseAgent, BrowserUseError, ModelTier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser"])


class RunTaskRequest(BaseModel):
    task: str = Field(..., description="Что сделать (на русском/английском)")
    model: str = Field(default=ModelTier.CHEAP.value, description="LLM модель")
    proxy_country: str = Field(default="kz", description="Страна прокси")
    human_in_loop: bool = Field(default=False, description="Включить HIL режим")
    allowed_domains: Optional[list[str]] = Field(default=None, description="Ограничить домены")
    enable_recording: bool = Field(default=True)
    max_duration_min: int = Field(default=15, ge=1, le=240)


class ContinueTaskRequest(BaseModel):
    task: str


@router.post("/run")
async def run_browser_task(req: RunTaskRequest) -> dict[str, Any]:
    """
    Запустить задачу в реальном браузере.

    Простой пример:
        POST /api/browser/run
        {
          "task": "Зайди на kaspi.kz и найди цены на ноутбук Lenovo",
          "model": "gpt-5.4-mini"
        }

    Human-in-the-loop (получишь live_url):
        {
          "task": "Зайди в мой кабинет на goszakup",
          "human_in_loop": true
        }
    """
    try:
        agent = BrowserUseAgent()
        result = await agent.run_task(
            task=req.task,
            model=req.model,
            proxy_country=req.proxy_country,
            human_in_loop=req.human_in_loop,
            allowed_domains=req.allowed_domains,
            enable_recording=req.enable_recording,
            max_duration_min=req.max_duration_min,
        )
        return {
            "session_id": result.session_id,
            "status": result.status,
            "output": result.output,
            "cost_usd": result.cost_usd,
            "duration_sec": result.duration_sec,
            "recording_url": result.recording_url,
            "step_count": result.step_count,
            "live_url": result.live_url,
        }
    except BrowserUseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("browser task failed")
        raise HTTPException(status_code=500, detail=f"Internal: {e}")


@router.get("/status/{session_id}")
async def get_browser_status(session_id: str) -> dict:
    """Получить статус сессии."""
    try:
        agent = BrowserUseAgent()
        return await agent.get_status(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/continue/{session_id}")
async def continue_browser_task(session_id: str, req: ContinueTaskRequest) -> dict:
    """Продолжить HIL сессию новой задачей."""
    try:
        agent = BrowserUseAgent()
        result = await agent.continue_session(session_id, req.task)
        return {
            "session_id": result.session_id,
            "status": result.status,
            "output": result.output,
            "cost_usd": result.cost_usd,
            "duration_sec": result.duration_sec,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/{session_id}")
async def stop_browser_session(session_id: str, strategy: str = "session") -> dict:
    """Остановить сессию. strategy=task|session."""
    try:
        agent = BrowserUseAgent()
        ok = await agent.stop_session(session_id, strategy=strategy)
        return {"stopped": ok, "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_models() -> dict:
    """Список доступных моделей с ценами."""
    return {
        "models": [
            {
                "id": ModelTier.CHEAP.value,
                "name": "GPT-5.4 mini",
                "tier": "cheap",
                "cost_per_task_estimate_usd": "$0.10-0.20",
                "best_for": "Простые задачи: парсинг, поиск",
            },
            {
                "id": ModelTier.BALANCED.value,
                "name": "Claude Sonnet 4.6",
                "tier": "balanced",
                "cost_per_task_estimate_usd": "$0.30-0.80",
                "best_for": "Сложные задачи: авторизация, 2FA, формы",
            },
            {
                "id": ModelTier.BROWSER_NATIVE.value,
                "name": "Browser Use 2.0",
                "tier": "native",
                "cost_per_task_estimate_usd": "$0.06-0.12",
                "best_for": "Своя LLM browser-use, оптимизированная",
            },
        ]
    }
