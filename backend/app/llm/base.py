"""Абстракция LLM-провайдера.

Все агенты работают через `LLMProvider`. Это позволяет менять провайдера
(Mistral сейчас → alemLLM потом) без изменения бизнес-логики.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


@dataclass
class EmbeddingResponse:
    vector: list[float]
    model: str


class LLMProvider(ABC):
    """Базовый интерфейс провайдера."""

    name: str = "base"

    @abstractmethod
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
        """Генерация ответа. При json_mode=True модель обязана вернуть валидный JSON.

        extra_body: провайдер-специфичные параметры (например, chat_template_kwargs для Qwen).
        """

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResponse:
        """Эмбеддинг одного текста."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResponse]:
        """Эмбеддинг пачки текстов (оптимизация под лимиты API)."""

    async def healthcheck(self) -> bool:
        """Проверка доступности. По умолчанию — embed('ping')."""
        try:
            await self.embed("ping")
            return True
        except Exception:
            return False
