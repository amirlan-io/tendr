"""Извлечение технических характеристик из ТЗ.

Используется для глубокого поиска товаров: вместо поиска по названию
ищем по конкретным характеристикам (размеры, материал, класс и т.д.).
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from app.agents.base import Agent
from app.core.config import get_settings


class SpecExtractor:
    """Извлекает структурированные характеристики из текста ТЗ.

    Использует LLM для парсинга неструктурированного текста в
    стандартизированный JSON с характеристиками.
    """

    SYSTEM_PROMPT = """Ты — эксперт по техническим заданиям госзакупок.
Твоя задача — извлечь из произвольного текста ТЗ ключевые технические
характеристики закупаемого товара/услуги.

Верни СТРОГО валидный JSON:
{
  "product_name": "краткое название товара",
  "category": "товары|услуги|работы",
  "key_specs": {
    "мощность": "значение с единицей",
    "размеры": "ДxШxВ в мм",
    "материал": "...",
    "класс": "...",
    "производительность": "...",
    "давление": "...",
    "температура": "..."
  },
  "search_keywords": ["keyword 1", "keyword 2", "..."],
  "search_exclude": ["что НЕ искать"],
  "min_quantity": число,
  "preferred_brands": ["бренд1", "бренд2"] или [],
  "comparable_attributes": ["атрибут для сравнения с конкурентами"]
}

Правила:
- Только РЕАЛЬНЫЕ характеристики из ТЗ, не выдумывай
- search_keywords — 3-5 терминов для поиска в каталогах
- search_exclude — что НЕ искать (например, если ищем фильтр воздушный — не искать "водяной фильтр")
- comparable_attributes — что важно для сравнения с конкурентами
- Если характеристика не указана — не включай в JSON"""

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm = llm_client

    async def extract(self, lot_text: str) -> dict[str, Any]:
        """Извлекает характеристики из текста ТЗ.

        Args:
            lot_text: текст ТЗ (или часть)

        Returns:
            {
                "product_name": "...",
                "category": "...",
                "key_specs": {...},
                "search_keywords": [...],
                "search_exclude": [...],
                "min_quantity": int | None,
                "preferred_brands": [...],
                "comparable_attributes": [...]
            }
        """
        from app.llm import get_llm

        llm = get_llm()
        prompt = f"{self.SYSTEM_PROMPT}\n\n=== ТЕКСТ ТЗ ===\n{lot_text[:8000]}\n\n=== JSON ==="

        try:
            from app.llm.base import Message

            response = await llm.chat(
                messages=[
                    Message(role="system", content=self.SYSTEM_PROMPT),
                    Message(role="user", content=f"Текст ТЗ:\n\n{lot_text[:8000]}\n\nВерни JSON."),
                ],
                json_mode=True,
                max_tokens=3000,
            )
            data = json.loads(response.content)
            return self._validate(data)
        except Exception as e:
            logger.warning("Spec extraction failed: {}", e)
            return self._fallback(lot_text)

    def _validate(self, data: dict) -> dict:
        """Валидирует и нормализует JSON."""
        return {
            "product_name": str(data.get("product_name", "товар"))[:200],
            "category": str(data.get("category", "товары"))[:50],
            "key_specs": data.get("key_specs") or {},
            "search_keywords": [str(k) for k in (data.get("search_keywords") or [])][:10],
            "search_exclude": [str(k) for k in (data.get("search_exclude") or [])][:10],
            "min_quantity": data.get("min_quantity")
            if isinstance(data.get("min_quantity"), int)
            else None,
            "preferred_brands": [str(b) for b in (data.get("preferred_brands") or [])][:5],
            "comparable_attributes": [str(a) for a in (data.get("comparable_attributes") or [])][
                :10
            ],
        }

    def _fallback(self, lot_text: str) -> dict:
        """Простой regex-fallback если LLM не сработал."""
        keywords = []
        # Ищем числа с единицами
        specs = {}
        for m in re.finditer(
            r"(\d+(?:[.,]\d+)?)\s*(мм|см|м|кг|г|л|м³|м3|°C|Вт|Квт|кВт|МПа|кг/м³)", lot_text
        ):
            unit = m.group(2)
            if unit not in specs:
                specs[unit] = m.group(0)
        # Берём первые значимые слова
        words = re.findall(r"[А-Яа-яЁё]{4,}", lot_text)[:10]
        keywords = list(set(words))[:5]

        return {
            "product_name": "товар",
            "category": "товары",
            "key_specs": specs,
            "search_keywords": keywords,
            "search_exclude": [],
            "min_quantity": None,
            "preferred_brands": [],
            "comparable_attributes": list(specs.keys())[:5],
        }
