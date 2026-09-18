"""Анализ цен по истории лотов в нашей БД.

Используется для:
- Сравнения найденных товаров с историческими ценами
- Прогноза бюджета для нового лота
- Конкурентного анализа
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis


@dataclass
class PriceStats:
    """Статистика цен по похожим лотам."""

    count: int = 0
    avg_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    median_price: float | None = None
    sources: list[dict] = None  # откуда данные
    recommendation: str = ""

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


async def get_price_stats(
    session: AsyncSession,
    product_keywords: str,
    *,
    limit: int = 50,
) -> PriceStats:
    """Ищет в нашей БД лоты с похожим названием и возвращает статистику по ценам.

    Args:
        session: БД сессия
        product_keywords: ключевые слова для поиска (например, "фильтр воздушный")
        limit: макс. сколько лотов рассмотреть

    Returns:
        PriceStats со статистикой
    """
    # Берём первое значимое слово (>= 4 букв)
    words = re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", product_keywords)
    if not words:
        return PriceStats()
    main_word = words[0]

    # Ищем в нашей БД лоты с похожим названием и известной ценой
    stmt = (
        select(Analysis)
        .where(Analysis.title.ilike(f"%{main_word}%"))
        .where(Analysis.budget_kzt.is_not(None))
        .order_by(Analysis.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return PriceStats(
            count=0,
            recommendation="Нет исторических данных. Используйте найденные товары для оценки.",
        )

    prices = [r.budget_kzt for r in rows if r.budget_kzt and r.budget_kzt > 0]
    if not prices:
        return PriceStats(count=len(rows))

    prices.sort()
    n = len(prices)
    avg = sum(prices) / n
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2

    # Рекомендация на основе позиции относительно рынка
    if median > 0:
        rec = (
            f"На основе {n} похожих лотов: средняя цена {avg:,.0f} ₸, "
            f"диапазон {min(prices):,.0f}–{max(prices):,.0f} ₸, "
            f"медиана {median:,.0f} ₸. "
            f"Рекомендуемая конкурентная цена: {median * 0.97:,.0f} ₸ (на 3% ниже медианы)."
        )
    else:
        rec = ""

    return PriceStats(
        count=n,
        avg_price=avg,
        min_price=min(prices),
        max_price=max(prices),
        median_price=median,
        sources=[
            {
                "lot_id": r.lot_id,
                "title": r.title[:80],
                "budget_kzt": r.budget_kzt,
                "customer": r.customer[:60] if r.customer else "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows[:5]
        ],
        recommendation=rec,
    )
