"""
API endpoint для browser actions.
POST /api/browser/run — запуск задачи
GET /api/browser/status/{session_id} — статус
POST /api/browser/continue/{session_id} — продолжить HIL сессию
POST /api/browser/stop/{session_id} — остановить
"""

import asyncio
import ipaddress
import logging
import re
import time
from collections import defaultdict, deque
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents.browser_use import BrowserUseAgent, BrowserUseError, ModelTier
from app.core.client_id import require_authenticated_client_id
from app.db import get_db
from app.services.operations import metered

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/browser", tags=["browser"])

BROWSER_ALLOWED_HOSTS = {
    "goszakup.gov.kz",
    "www.goszakup.gov.kz",
    "ows.goszakup.gov.kz",
    "v3bl.goszakup.gov.kz",
    "zakup.gov.kz",
    "www.zakup.gov.kz",
}
BROWSER_ALLOWED_TASKS = {
    "check_lot_status",
    "validate_lot_reference",
    "review_lot_requirements",
}
MAX_PARALLEL_BROWSER_TASKS_PER_CLIENT = 1
MAX_BROWSER_REQUESTS_PER_MINUTE = 5
MAX_BROWSER_TASK_DURATION_MIN = 15
MAX_BROWSER_STEPS = 25
MAX_BROWSER_ACTION_TIMEOUT_SECONDS = 45

_BROWSER_SESSIONS: dict[str, dict[str, Any]] = {}
_BROWSER_CLIENT_ACTIVE: dict[str, float] = {}
_BROWSER_CLIENT_ACTIVITY: dict[str, deque[float]] = defaultdict(deque)


class RunTaskRequest(BaseModel):
    task: str = Field(..., description="Server-side browser action template")
    lot_id: Optional[str] = Field(default=None, description="Lot ID or lot number")
    url: Optional[str] = Field(default=None, description="Trusted public lot URL")
    model: str = Field(default=ModelTier.CHEAP.value, description="LLM модель")
    proxy_country: str = Field(default="kz", description="Страна прокси")
    human_in_loop: bool = Field(default=False, description="Включить HIL режим")
    allowed_domains: Optional[list[str]] = Field(default=None, description="Ограничить домены")
    enable_recording: bool = Field(default=True)
    max_duration_min: int = Field(default=15, ge=1, le=MAX_BROWSER_TASK_DURATION_MIN)


class ContinueTaskRequest(BaseModel):
    task: str = Field(..., description="Server-side browser action template")


def _enforce_browser_rate_limit(client_id: str) -> None:
    now = time.monotonic()
    history = _BROWSER_CLIENT_ACTIVITY[client_id]
    while history and now - history[0] > 60:
        history.popleft()
    if len(history) >= MAX_BROWSER_REQUESTS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="RATE_LIMITED")
    history.append(now)


def _reserve_browser_slot(client_id: str) -> None:
    now = time.monotonic()
    expires_at = _BROWSER_CLIENT_ACTIVE.get(client_id)
    if expires_at is not None and expires_at > now:
        raise HTTPException(status_code=429, detail="RATE_LIMITED")
    _BROWSER_CLIENT_ACTIVE[client_id] = now + 60


def _release_browser_slot(client_id: str) -> None:
    now = time.monotonic()
    expires_at = _BROWSER_CLIENT_ACTIVE.get(client_id)
    if expires_at is None:
        return
    if expires_at <= now:
        _BROWSER_CLIENT_ACTIVE.pop(client_id, None)
        return
    _BROWSER_CLIENT_ACTIVE[client_id] = now + 60


def _sanitize_allowed_domains(values: Optional[list[str]]) -> Optional[list[str]]:
    if values is None:
        return ["goszakup.gov.kz", "zakup.gov.kz"]

    cleaned: list[str] = []
    for raw in values:
        candidate = (raw or "").strip().lower()
        if not candidate:
            raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
        if not candidate.startswith(("http://", "https://")):
            candidate = "https://" + candidate
        host = urlsplit(candidate).hostname
        if not host or host not in BROWSER_ALLOWED_HOSTS:
            raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
        cleaned.append(host)
    return list(dict.fromkeys(cleaned)) or ["goszakup.gov.kz", "zakup.gov.kz"]


def _validate_lot_id(value: Optional[str]) -> str | None:
    if value is None:
        return None
    candidate = (value or "").strip()
    if not re.fullmatch(r"\d{6,}(?:-\d+)?", candidate):
        raise HTTPException(status_code=422, detail="INVALID_LOT_ID")
    return candidate


def _validate_host_url(value: Optional[str]) -> str | None:
    if value is None:
        return None
    candidate = (value or "").strip()
    if not candidate:
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    splitted = urlsplit(candidate)
    if splitted.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    if splitted.username or splitted.password:
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    if not splitted.hostname:
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    hostname = splitted.hostname.lower()
    if hostname not in BROWSER_ALLOWED_HOSTS:
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    ):
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    if splitted.port not in (None, 80, 443):
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_URL")
    return candidate


def _validate_browser_action(task: str, lot_id: str | None, url: str | None) -> str:
    if task not in BROWSER_ALLOWED_TASKS:
        raise HTTPException(status_code=422, detail="INVALID_BROWSER_ACTION")
    if task == "check_lot_status":
        if lot_id is None and url is None:
            raise HTTPException(status_code=422, detail="INVALID_LOT_ID")
    if lot_id is not None:
        _validate_lot_id(lot_id)
    if url is not None:
        _validate_host_url(url)
    return task


def _get_browser_session_for_client(session_id: str, client_id: str) -> dict[str, Any]:
    session = _BROWSER_SESSIONS.get(session_id)
    if session is None or session.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _run_task_with_timeout(agent: BrowserUseAgent, **kwargs: Any) -> Any:
    try:
        return await asyncio.wait_for(
            agent.run_task(**kwargs),
            timeout=MAX_BROWSER_ACTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.exception("Browser task timed out")
        raise BrowserUseError("browser task timeout")


@router.post("/run")
@metered("browser_run")
async def run_browser_task(
    req: RunTaskRequest,
    db=Depends(get_db),
    client_id: str = Depends(require_authenticated_client_id),
) -> dict[str, Any]:
    """Запустить задачу в реальном браузере по безопасному шаблону."""
    _enforce_browser_rate_limit(client_id)
    _validate_browser_action(req.task, req.lot_id, req.url)
    lot_id = _validate_lot_id(req.lot_id)
    url = _validate_host_url(req.url)
    allowed_domains = _sanitize_allowed_domains(req.allowed_domains)
    safe_task = req.task
    safe_max_duration = min(int(req.max_duration_min), MAX_BROWSER_TASK_DURATION_MIN)

    try:
        _reserve_browser_slot(client_id)
        agent = BrowserUseAgent()
        metadata = {"client_id": client_id, "lot_id": lot_id or "", "url": url or ""}
        result = await _run_task_with_timeout(
            agent,
            task=safe_task,
            model=req.model,
            proxy_country=req.proxy_country,
            human_in_loop=req.human_in_loop,
            allowed_domains=allowed_domains,
            enable_recording=req.enable_recording,
            max_duration_min=safe_max_duration,
            metadata=metadata,
        )
        if result.step_count > MAX_BROWSER_STEPS:
            await agent.stop_session(result.session_id, strategy="session")
            raise HTTPException(status_code=429, detail="RATE_LIMITED")
        _BROWSER_SESSIONS[result.session_id] = {
            "client_id": client_id,
            "status": result.status,
            "step_count": result.step_count,
            "created_at": time.time(),
            "task": safe_task,
            "lot_id": lot_id,
            "url": url,
        }
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
    except HTTPException:
        raise
    except BrowserUseError:
        logger.exception("browser task failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")
    except Exception:
        logger.exception("browser task failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")
    finally:
        _release_browser_slot(client_id)


@router.get("/status/{session_id}")
async def get_browser_status(
    session_id: str,
    client_id: str = Depends(require_authenticated_client_id),
) -> dict:
    """Получить статус сессии только владельцем."""
    session = _get_browser_session_for_client(session_id, client_id)
    try:
        agent = BrowserUseAgent()
        state = await agent.get_status(session_id)
        session["status"] = state.get("status", session.get("status"))
        return {
            "id": session_id,
            "status": session["status"],
            "live_url": state.get("live_url"),
            "output": state.get("output"),
        }
    except BrowserUseError:
        logger.exception("browser status lookup failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")
    except Exception:
        logger.exception("browser status lookup failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")


@router.post("/continue/{session_id}")
@metered("browser_continue")
async def continue_browser_task(
    session_id: str,
    req: ContinueTaskRequest,
    db=Depends(get_db),
    client_id: str = Depends(require_authenticated_client_id),
) -> dict:
    """Продолжить HIL сессию только владельцем."""
    session = _get_browser_session_for_client(session_id, client_id)
    _validate_browser_action(req.task, session.get("lot_id"), session.get("url"))
    try:
        agent = BrowserUseAgent()
        result = await _run_task_with_timeout(
            agent,
            session_id=session_id,
            task=req.task,
            model=ModelTier.CHEAP.value,
            metadata={"client_id": client_id, "lot_id": session.get("lot_id") or ""},
        )
        session["status"] = result.status
        return {
            "session_id": result.session_id,
            "status": result.status,
            "output": result.output,
            "cost_usd": result.cost_usd,
            "duration_sec": result.duration_sec,
        }
    except BrowserUseError:
        logger.exception("browser continue failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")
    except Exception:
        logger.exception("browser continue failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")


@router.post("/stop/{session_id}")
async def stop_browser_session(
    session_id: str,
    strategy: str = "session",
    client_id: str = Depends(require_authenticated_client_id),
) -> dict:
    """Остановить сессию только владельцем."""
    session = _get_browser_session_for_client(session_id, client_id)
    try:
        agent = BrowserUseAgent()
        ok = await agent.stop_session(session_id, strategy=strategy)
        if ok:
            session["status"] = "stopped"
        return {"stopped": bool(ok), "session_id": session_id}
    except BrowserUseError:
        logger.exception("browser stop failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")
    except Exception:
        logger.exception("browser stop failed")
        raise HTTPException(status_code=500, detail="BROWSER_TASK_FAILED")


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
