"""Провайдер с автоматическим fallback при сбоях основного.

Например: основной = alemLLM (через OpenAI-совместимый API), fallback = Mistral.
Если alemLLM возвращает 5xx подряд — переключаемся на Mistral для текущего процесса.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from app.llm.base import (
    EmbeddingResponse,
    LLMProvider,
    LLMResponse,
    Message,
)


class FailoverProvider(LLMProvider):
    """Прозрачный fallback: primary (например, alemLLM) → secondary (Mistral)."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider | None = None) -> None:
        self._primary = primary
        self._secondary = secondary
        self._primary_failed_count = 0
        self._max_failures = 3
        self._cooldown_seconds = 60
        self._last_failover_at: float = 0.0
        self._lock = asyncio.Lock()
        self.name = f"failover:{primary.name}"

    def _should_failover(self) -> bool:
        if self._secondary is None:
            return False
        if self._primary_failed_count < self._max_failures:
            return False
        # После N ошибок — переключаемся на время cooldown
        return True

    def _record_failure(self) -> None:
        import time
        self._primary_failed_count += 1
        self._last_failover_at = time.monotonic()
        if self._primary_failed_count == self._max_failures:
            logger.warning(
                "Primary LLM '{}' failed {} times, switching to fallback '{}'",
                self._primary.name,
                self._primary_failed_count,
                self._secondary.name if self._secondary else "none",
            )

    def _record_success(self) -> None:
        if self._primary_failed_count > 0:
            logger.info("Primary LLM '{}' recovered", self._primary.name)
        self._primary_failed_count = 0

    async def _try_primary(self, coro_factory, *args, **kwargs):
        import time
        if self._should_failover() and time.monotonic() - self._last_failover_at < self._cooldown_seconds:
            return await coro_factory(self._secondary, *args, **kwargs)
        try:
            result = await coro_factory(self._primary, *args, **kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            # Fallback нужен для текущего пользовательского запроса сразу.
            # Старое поведение ждало три отдельных сбоя: первый анализ лота
            # поэтому возвращался пустым, хотя резервный провайдер был рабочим.
            if self._secondary is not None:
                logger.warning(
                    "Primary LLM '{}' failed ({}), using fallback '{}'",
                    self._primary.name,
                    e,
                    self._secondary.name,
                )
                return await coro_factory(self._secondary, *args, **kwargs)
            raise

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        async def call(p: LLMProvider):
            return await p.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                extra_body=extra_body,
                **kwargs,
            )

        return await self._try_primary(call)

    async def embed(self, text: str) -> EmbeddingResponse:
        # У эмбеддингов делаем fallback на secondary, если primary не умеет embed
        # (например, alemLLM/qwen3-6 не умеет embeddings — тогда fallback на Mistral).
        try:
            return await self._primary.embed(text)
        except Exception as e:
            if self._secondary is not None:
                logger.debug(
                    "Primary embed failed ({}), using fallback '{}'",
                    e, self._secondary.name,
                )
                return await self._secondary.embed(text)
            raise

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResponse]:
        # Аналогично — fallback на secondary для batch embeddings.
        try:
            return await self._primary.embed_batch(texts)
        except Exception as e:
            if self._secondary is not None:
                logger.debug(
                    "Primary embed_batch failed ({}), using fallback '{}'",
                    e, self._secondary.name,
                )
                return await self._secondary.embed_batch(texts)
            raise

    async def healthcheck(self) -> bool:
        # Сначала пробуем primary, потом secondary
        try:
            return await self._primary.healthcheck()
        except Exception:
            if self._secondary:
                return await self._secondary.healthcheck()
            return False
