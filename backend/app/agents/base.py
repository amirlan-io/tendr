"""Базовый класс агента + утилиты для JSON-парсинга LLM-ответов."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from loguru import logger

from app.llm import Message, get_llm


class Agent(ABC):
    """Базовый класс. Агенты используют LLM + RAG и возвращают структурированный результат."""

    name: str = "base"
    system_prompt: str = ""

    @abstractmethod
    async def run(self, *args, **kwargs): ...

    async def _chat_json(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> dict:
        """Чат с принудительным JSON-режимом и парсингом. При сбое LLM возвращает {}.

        max_tokens: сколько токенов модель может сгенерировать (по умолчанию 4000,
        этого хватает на JSON с 3-5 требованиями + red_flags + summary).
        """
        llm = get_llm()
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_prompt),
        ]
        try:
            resp = await llm.chat(
                messages,
                temperature=temperature,
                json_mode=True,
                max_tokens=max_tokens,
            )
            return _safe_parse_json(resp.content)
        except Exception as e:
            logger.error("LLM chat failed in agent '{}': {}", self.name, e)
            return {}

    async def _chat_text(self, user_prompt: str, *, temperature: float = 0.3) -> str:
        llm = get_llm()
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_prompt),
        ]
        try:
            resp = await llm.chat(messages, temperature=temperature)
            return resp.content
        except Exception as e:
            logger.error("LLM chat failed in agent '{}': {}", self.name, e)
            return f"[Ошибка LLM: {e}]"


def _safe_parse_json(content: str) -> dict:
    """LLM иногда оборачивает JSON в ```json ... ```. Чистим и парсим."""
    text = content.strip()
    # убираем markdown-обёртку
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # вырезаем JSON-объект, даже если вокруг есть «вот ваш JSON:»
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON from LLM: {}\nContent was:\n{}", e, content[:1000])
        # Попытка 2: обрезать до последней валидной позиции
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text)
            logger.info("Recovered partial JSON after truncation")
            return obj
        except Exception:
            pass
        # Попытка 3: обрезать по последней закрывающей скобке }
        try:
            last_close = text.rfind("}")
            if last_close > 0:
                truncated = text[: last_close + 1]
                return json.loads(truncated)
        except Exception:
            pass
        return {}
