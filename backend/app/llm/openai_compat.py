"""OpenAI-совместимый провайдер — для alemLLM, локального llama.cpp, vLLM и т.п."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.llm.base import (
    EmbeddingResponse,
    LLMProvider,
    LLMResponse,
    Message,
)

log = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """Провайдер для любых OpenAI-совместимых API (alemLLM, llama.cpp server, vLLM)."""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        disable_thinking: bool = False,
    ) -> None:
        s = get_settings()
        self._api_key = api_key or s.llm_api_key or "EMPTY"
        self._base_url = (base_url or s.llm_base_url).rstrip("/")
        self._model = model or s.llm_model
        self._embed_model = embed_model or s.llm_embedding_model
        self._disable_thinking = disable_thinking
        self._client = httpx.AsyncClient(timeout=120.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

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
        # Авто-отключение thinking для qwen-моделей
        if self._disable_thinking or "qwen" in (self._model or "").lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if extra_body:
            # Сливаем с верхнего уровня, чтобы qwen-style `{"chat_template_kwargs": {...}}` работал
            payload.update(extra_body)

        resp = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        if resp.status_code >= 500:
            log.warning("LLM 5xx: %s, body: %s", resp.status_code, resp.text[:200])
            resp.raise_for_status()
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self._model),
            usage=data.get("usage", {}),
            raw=data,
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
    )
    async def embed(self, text: str) -> EmbeddingResponse:
        return (await self.embed_batch([text]))[0]

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
    )
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResponse]:
        resp = await self._client.post(
            f"{self._base_url}/embeddings",
            headers=self._headers(),
            json={"model": self._embed_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            EmbeddingResponse(vector=item["embedding"], model=self._embed_model)
            for item in data["data"]
        ]
