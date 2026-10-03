"""Тесты проверки доступности LLM.

Проверка доступности по embed('ping') давала ложное «unavailable» у
провайдеров без поддержки эмбеддингов, хотя чат работал. Теперь
проверяется chat — то, от чего реально зависит анализ лотов.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.base import LLMProvider, LLMResponse, Message


class _Fake(LLMProvider):
    """Провайдер с управляемым поведением чата и embed."""

    def __init__(self, *, chat_ok: bool, embed_ok: bool) -> None:
        self.chat_ok = chat_ok
        self.embed_ok = embed_ok
        self.chat_calls: list[list[Message]] = []
        self.embed_calls: list[str] = []

    async def chat(self, messages: list[Message], **kw: Any) -> LLMResponse:
        self.chat_calls.append(messages)
        if not self.chat_ok:
            raise RuntimeError("chat down")
        return LLMResponse(content="ok", model="fake")

    async def embed(self, text: str) -> Any:
        self.embed_calls.append(text)
        if not self.embed_ok:
            raise RuntimeError("embed down")
        return [0.0]

    async def embed_batch(self, texts: list[str]) -> list[Any]:
        return [await self.embed(t) for t in texts]


@pytest.mark.asyncio
async def test_healthcheck_reports_ok_when_chat_works() -> None:
    """Chat работает, embed нет — это НЕ поломка, приложение живёт."""
    provider = _Fake(chat_ok=True, embed_ok=False)
    assert await provider.healthcheck() is True
    assert await provider.supports_embeddings() is False


@pytest.mark.asyncio
async def test_healthcheck_ok_when_only_embed_works() -> None:
    provider = _Fake(chat_ok=False, embed_ok=True)
    assert await provider.healthcheck() is True


@pytest.mark.asyncio
async def test_healthcheck_false_when_everything_fails() -> None:
    provider = _Fake(chat_ok=False, embed_ok=False)
    assert await provider.healthcheck() is False


@pytest.mark.asyncio
async def test_healthcheck_passes_message_objects_not_dicts() -> None:
    """Провайдеры сериализуют Message через __dict__.

    Словарь приводит к AttributeError иhealthcheck всегда был бы отрицательным
    — такую ошибку поймал живой прогон.
    """
    provider = _Fake(chat_ok=True, embed_ok=True)
    await provider.healthcheck()
    first = provider.chat_calls[0][0]
    assert isinstance(first, Message)
    assert first.role == "user"


@pytest.mark.asyncio
async def test_healthcheck_prefers_chat_over_embed() -> None:
    """Сначала пробуем chat: он и есть рабочая зависимость приложения."""
    provider = _Fake(chat_ok=True, embed_ok=True)
    assert await provider.healthcheck() is True
    assert provider.chat_calls, "healthcheck должен проверять chat"


@pytest.mark.asyncio
async def test_ai_chat_uses_qwen_key_and_normalizes_full_endpoint(monkeypatch) -> None:
    from app.llm import mistral as provider_module
    from app.llm.openai_compat import OpenAICompatProvider

    settings = SimpleNamespace(
        llm_provider="mistral",
        llm_api_key="mistral-key",
        llm_api_key_fallback="qwen-key",
        alem_base_url="https://llm.alem.ai/v1/chat/completions",
        alem_model="qwen3-8",
        llm_embedding_model="mistral-embed",
    )
    monkeypatch.setattr(provider_module, "get_settings", lambda: settings)
    provider_module._assistant_provider = None

    provider = provider_module.get_assistant_llm()
    try:
        assert isinstance(provider, OpenAICompatProvider)
        assert provider._api_key == "qwen-key"
        assert provider._base_url == "https://llm.alem.ai/v1"
        assert provider._model == "qwen3-8"
    finally:
        await provider.close()
        provider_module._assistant_provider = None
