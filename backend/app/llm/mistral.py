"""Реализация LLMProvider для Mistral API.

Использует официальный OpenAI-совместимый endpoint Mistral.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.llm.base import (
    EmbeddingResponse,
    LLMProvider,
    LLMResponse,
    Message,
)

log = logging.getLogger(__name__)


class MistralProvider(LLMProvider):
    name = "mistral"

    # Стандартные Mistral-параметры — используются когда провайдер создаётся
    # как fallback для AlemLLM (в этом случае в s.llm_base_url лежит alem-URL).
    _DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
    _DEFAULT_MODEL = "mistral-large-latest"
    _DEFAULT_EMBED_MODEL = "mistral-embed"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        s = get_settings()
        key = api_key or s.llm_api_key
        if not key:
            raise RuntimeError("LLM_API_KEY is empty. Fill .env first.")
        self._api_key = key
        # Если base_url не передан явно — берём из настроек, но если он не
        # похож на Mistral (например, это alem.ai), используем дефолтный Mistral URL.
        cfg_url = (base_url or s.llm_base_url or "").rstrip("/")
        if "mistral.ai" in cfg_url:
            self._base_url = cfg_url
        else:
            # В .env LLM_BASE_URL может быть alem.ai, если Mistral — secondary.
            # В этом случае используем стандартный Mistral URL.
            self._base_url = self._DEFAULT_BASE_URL
        # Аналогично для model: если в настройках стоит qwen3-6 (alem), берём mistral-large-latest.
        cfg_model = model or s.llm_model
        if cfg_model and "qwen" in cfg_model.lower():
            self._model = self._DEFAULT_MODEL
        else:
            self._model = cfg_model or self._DEFAULT_MODEL
        # Embeddings — всегда через Mistral (alemLLM не умеет embed).
        self._embed_model = embed_model or self._DEFAULT_EMBED_MODEL
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=2, max=8),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
    )
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
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [m.__dict__ for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if extra_body:
            payload.update(extra_body)

        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self._model),
            usage=data.get("usage", {}),
            raw=data,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def embed(self, text: str) -> EmbeddingResponse:
        return (await self.embed_batch([text]))[0]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResponse]:
        resp = await self._client.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._embed_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            EmbeddingResponse(vector=item["embedding"], model=self._embed_model)
            for item in data["data"]
        ]


# Фабрика
_provider: LLMProvider | None = None


def _wrap_with_failover(primary: LLMProvider, secondary: LLMProvider) -> LLMProvider:
    from app.llm.failover import FailoverProvider

    return FailoverProvider(primary=primary, secondary=secondary)


def _make_alem_from_settings(s) -> LLMProvider:
    """Создаёт OpenAICompatProvider с alem-параметрами (qwen3-6 с отключённым thinking).

    Внимание про ключи:
    - LLM_API_KEY        — ключ основного провайдера (если LLM_PROVIDER=openai-compatible,
                            то это AlemLLM-ключ, и мы используем его для primary).
    - LLM_API_KEY_FALLBACK — ключ резервного провайдера (для Mistral fallback'а).
    """
    from app.llm.openai_compat import OpenAICompatProvider

    # Когда LLM_PROVIDER=openai-compatible, llm_api_key = AlemLLM-ключ.
    # Когда LLM_PROVIDER=mistral, этот метод вызывается для создания secondary
    # и тогда llm_api_key_fallback = AlemLLM-ключ. Проверяем оба варианта.
    alem_key = s.llm_api_key
    if s.llm_provider == "mistral":
        # mistral primary → alem secondary должен использовать fallback-ключ
        alem_key = s.llm_api_key_fallback or s.llm_api_key

    return OpenAICompatProvider(
        api_key=alem_key,
        base_url=s.alem_base_url,
        model=s.alem_model,
        embed_model=s.llm_embedding_model,  # alem не умеет embed; пусть RAG использует Mistral
        disable_thinking=True,  # qwen3-6: отключаем thinking mode через chat_template_kwargs
    )


def get_llm() -> LLMProvider:
    """Singleton-провайдер по настройкам.

    Стратегия:
    - llm_provider=mistral → Mistral (primary), alemLLM (secondary)
    - llm_provider=openai-compatible → alemLLM/qwen3-6 (primary), Mistral (secondary)
    - llm_provider=alem → то же, что openai-compatible

    Ключи:
    - LLM_API_KEY        — ключ для primary
    - LLM_API_KEY_FALLBACK — ключ для secondary
    """
    global _provider
    if _provider is not None:
        return _provider
    s = get_settings()

    if s.llm_provider == "mistral":
        primary = MistralProvider()
        if s.llm_api_key_fallback:
            secondary = _make_alem_from_settings(s)
            _provider = _wrap_with_failover(primary, secondary)
        else:
            _provider = primary
    else:
        # openai-compatible = alemLLM (qwen3-6) по умолчанию
        primary = _make_alem_from_settings(s)
        if s.llm_api_key_fallback:
            # Mistral как fallback — используем LLM_API_KEY_FALLBACK (Mistral-ключ)
            fallback = MistralProvider(api_key=s.llm_api_key_fallback)
            _provider = _wrap_with_failover(primary, fallback)
        else:
            _provider = primary

    logger.info("LLM provider initialized: {} (primary={} secondary={})",
                _provider.name, primary.name,
                getattr(_provider, "_secondary", None) and _provider._secondary.name or "none")
    return _provider


async def close_llm() -> None:
    global _provider
    if _provider is not None and hasattr(_provider, "close"):
        await _provider.close()
    _provider = None
