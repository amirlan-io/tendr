"""
BrowserUseAgent — обёртка над browser-use SDK для Tendr.

Использование:
    agent = BrowserUseAgent()
    result = await agent.run_task(
        task="Заполни заявку на goszakup...",
        model="gpt-5.4-mini",
        proxy_country="kz",
        human_in_loop=True,
    )

Модели (по ценам):
- gpt-5.4-mini — дешёвая, для простых задач (~$0.10-0.20)
- claude-sonnet-4.6 — для сложных (~$0.30-0.80)
- browser-use-2.0 (v2) — своя LLM browser-use (~$0.06-0.12)
"""

import asyncio
import logging
import os
from app.core.config import get_settings
from app.agents.browser_use.v4 import clamp_max_cost_usd
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BrowserUseError(Exception):
    """Ошибка browser-use (сеть, авторизация, таймаут)."""

    pass


class ModelTier(str, Enum):
    CHEAP = "gpt-5.4-mini"  # дешёвая, для простых задач
    BALANCED = "claude-sonnet-4.6"  # для сложных
    BROWSER_NATIVE = "browser-use-2.0"  # v2, своя LLM browser-use


@dataclass
class TaskResult:
    """Результат одной задачи browser-use."""

    session_id: str
    status: str
    output: Any
    cost_usd: float
    duration_sec: float
    recording_url: Optional[str] = None
    step_count: int = 0
    live_url: Optional[str] = None


class BrowserUseAgent:
    """
    Агент-обёртка browser-use для Tendr.

    Не хранит состояние между вызовами (кроме профилей — если нужно).
    Использует наш BROWSER_USE_API_KEY.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_settings().browser_use_api_key or os.getenv("BROWSER_USE_API_KEY")
        if not self.api_key:
            raise BrowserUseError(
                "BROWSER_USE_API_KEY не задан. Получи через scripts/browser_use/signup.py"
            )
        self._client = None

    async def _get_client(self):
        """Lazy init SDK клиента."""
        if self._client is None:
            try:
                from browser_use_sdk.v3 import AsyncBrowserUse

                self._client = AsyncBrowserUse(api_key=self.api_key)
            except ImportError:
                raise BrowserUseError("browser-use-sdk не установлен. pip install browser-use-sdk")
        return self._client

    async def run_task(
        self,
        task: str,
        model: str = ModelTier.CHEAP.value,
        proxy_country: str = "kz",
        human_in_loop: bool = False,
        allowed_domains: Optional[list[str]] = None,
        enable_recording: bool = True,
        max_duration_min: int = 15,
        metadata: Optional[dict[str, str]] = None,
        structured_output_schema: Optional[type] = None,
    ) -> TaskResult:
        """
        Запустить одну задачу в браузере.

        Args:
            task: что сделать (на естественном языке, на русском или английском)
            model: какую LLM использовать (см. ModelTier)
            proxy_country: код страны прокси (kz, ru, us, de...)
            human_in_loop: если True — вернёт live_url, ты можешь подключиться
            allowed_domains: ограничить агента только этими доменами
            enable_recording: записывать видео сессии (MP4)
            max_duration_min: макс. время (до 240 мин = 4 часа)
            metadata: кастомные метаданные (например {"user_id": "abc"})
            structured_output_schema: Pydantic класс для типизированного ответа

        Returns:
            TaskResult со статусом, output, стоимостью
        """
        import time

        client = await self._get_client()

        kwargs = dict(
            task=task,
            max_cost_usd=clamp_max_cost_usd(get_settings().browser_use_max_cost_usd),
            model=model,
            proxy_country_code=proxy_country,
            enable_recording=enable_recording,
            metadata=metadata or {},
        )

        if allowed_domains:
            kwargs["allowed_domains"] = allowed_domains

        if max_duration_min:
            kwargs["timeout"] = max_duration_min

        if structured_output_schema is not None:
            kwargs["output_schema"] = structured_output_schema

        logger.info(
            f"[browser-use] Запускаю задачу (модель={model}, proxy={proxy_country}, "
            f"hil={human_in_loop}, domains={allowed_domains})"
        )
        logger.info(f"[browser-use] Task: {task[:200]}...")

        start = time.time()
        try:
            if human_in_loop:
                # Создаём сессию, возвращаем live_url сразу
                session = await client.sessions.create(
                    task=task,
                    max_cost_usd=clamp_max_cost_usd(get_settings().browser_use_max_cost_usd),
                    model=model,
                    proxy_country_code=proxy_country,
                    enable_recording=enable_recording,
                    allowed_domains=allowed_domains,
                    timeout=max_duration_min,
                    metadata=metadata or {},
                )
                logger.info(f"[browser-use] HIL session: {session.id}, live_url={session.live_url}")
                return TaskResult(
                    session_id=session.id,
                    status="human_in_loop_pending",
                    output=None,
                    cost_usd=0.0,
                    duration_sec=time.time() - start,
                    live_url=session.live_url,
                    recording_url=None,
                )

            # Обычный запуск
            result = await client.run(**kwargs)
            elapsed = time.time() - start

            cost = getattr(result, "llm_cost_usd", 0.0) or 0.0
            try:
                cost = float(cost)
            except (TypeError, ValueError):
                cost = 0.0
            output = getattr(result, "output", None)
            status = str(getattr(result, "status", "unknown"))
            step_count = getattr(result, "step_count", 0) or 0

            # Recording
            recording_url = None
            if enable_recording:
                try:
                    urls = await client.sessions.wait_for_recording(result.id, timeout=15)
                    if urls:
                        recording_url = urls[0]
                except Exception as e:
                    logger.warning(f"[browser-use] recording unavailable: {e}")

            logger.info(
                            f"[browser-use] Готово за {elapsed:.1f}s, статус={status}, "
                            f"стоимость=${float(cost):.4f}, шагов={step_count}"
                        )

            return TaskResult(
                session_id=result.id,
                status=status,
                output=output,
                cost_usd=cost,
                duration_sec=elapsed,
                recording_url=recording_url,
                step_count=step_count,
            )

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"[browser-use] Ошибка через {elapsed:.1f}s: {e}")
            raise BrowserUseError(f"Task failed: {e}") from e

    async def continue_session(
        self,
        session_id: str,
        task: str,
        model: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> TaskResult:
        """
        Продолжить существующую сессию (для human-in-loop).
        Cookies и браузер сохраняются.
        """
        import time

        client = await self._get_client()

        kwargs = dict(session_id=session_id, task=task, max_cost_usd=clamp_max_cost_usd(get_settings().browser_use_max_cost_usd))
        if model:
            kwargs["model"] = model
        if metadata:
            kwargs["metadata"] = metadata

        start = time.time()
        try:
            result = await client.run(**kwargs)
            elapsed = time.time() - start

            return TaskResult(
                session_id=session_id,
                status=str(getattr(result, "status", "unknown")),
                output=getattr(result, "output", None),
                cost_usd=getattr(result, "llm_cost_usd", 0.0) or 0.0,
                duration_sec=elapsed,
                step_count=getattr(result, "step_count", 0) or 0,
            )
        except Exception as e:
            raise BrowserUseError(f"Continue failed: {e}") from e

    async def stop_session(self, session_id: str, strategy: str = "session") -> bool:
        """
        Остановить сессию.
        strategy="task" — только текущую задачу (сессия остаётся)
        strategy="session" — убить сессию полностью
        """
        client = await self._get_client()
        try:
            await client.sessions.stop(session_id, strategy=strategy)
            return True
        except Exception as e:
            logger.error(f"[browser-use] stop failed: {e}")
            return False

    async def get_status(self, session_id: str) -> dict:
        """Получить статус сессии."""
        client = await self._get_client()
        s = await client.sessions.get(session_id)
        return {
            "id": s.id,
            "status": str(s.status),
            "live_url": getattr(s, "live_url", None),
            "output": getattr(s, "output", None),
        }


# Синглтон для удобного импорта
_default_agent: Optional[BrowserUseAgent] = None


def get_browser_agent() -> BrowserUseAgent:
    """Получить singleton агента."""
    global _default_agent
    if _default_agent is None:
        _default_agent = BrowserUseAgent()
    return _default_agent
