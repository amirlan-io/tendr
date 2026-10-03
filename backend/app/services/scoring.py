"""Скоринг заказчика + оценка маржинальности.

Скоринг (0-100):
- Пока без токена goszakup — используем эвристику по результатам анализов в БД
- Когда появится токен — добавим сбор истории по заказчику

Маржинальность:
- Категория лота → средняя маржа по категории (из БД)
- Эвристика по ключевым словам из title
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis

# Внутренние стартовые ориентиры продукта. Это не рыночная статистика и не
# обещание прибыли: пользователь должен заменить их своими себестоимостью,
# логистикой, налогами и накладными расходами.
CATEGORY_MARGIN: dict[str, float] = {
    "it": 22.0,
    "компьютер": 18.0,
    "программное обеспечение": 25.0,
    "услуги": 28.0,
    "консалтинг": 32.0,
    "обучение": 30.0,
    "мебель": 22.0,
    "строительство": 18.0,
    "ремонт": 20.0,
    "медицина": 24.0,
    "оборудование": 18.0,
    "транспорт": 16.0,
    "канцтовары": 28.0,
    "продукты питания": 15.0,
    "одежда": 22.0,
    "уборка": 26.0,
    "охрана": 22.0,
    "связь": 20.0,
    "топливо": 8.0,
    "электричество": 10.0,
}

# Категория по умолчанию
DEFAULT_MARGIN = 18.0


def detect_category(title: str, description: str = "") -> str:
    """Определяет категорию по ключевым словам в title/description."""
    text = f"{title} {description}".lower()
    for keyword, _ in CATEGORY_MARGIN.items():
        if keyword in text:
            return keyword
    return "other"


def estimate_margin_pct(title: str, description: str = "") -> dict[str, Any]:
    """Оценить маржинальность лота по категории."""
    category = detect_category(title, description)
    margin = CATEGORY_MARGIN.get(category, DEFAULT_MARGIN)
    return {
        "category": category,
        "estimated_margin_pct": margin,
        "confidence": "low" if category == "other" else "medium",
        "is_estimate": True,
        "method": "category_baseline",
        "assumptions": [
            "Использован внутренний ориентир по категории",
            "Не учтены ваша закупочная цена, логистика, налоги и накладные расходы",
        ],
        "disclaimer": "Ориентир по категории, а не расчёт вашей фактической прибыли.",
    }


# Скоринг заказчика — без токена только эвристика
async def get_customer_score(session: AsyncSession, customer_name: str) -> dict[str, Any]:
    """Получить скоринг заказчика по его названию.

    Без токена: считаем по нашим сохранённым анализам.
    С токеном: добавим реальную историю из goszakup.
    """
    if not customer_name or customer_name == "(не указан)":
        return {
            "customer": customer_name,
            "trust_score": 50.0,
            "trust_label": "unknown",
            "total_lots": 0,
            "source": "no_data",
            "is_estimate": True,
            "evidence_count": 0,
            "method": "internal_analyses",
            "disclaimer": "Данных для оценки нет; надёжность заказчика не проверена.",
        }

    # Ищем в нашей БД
    stmt = select(Analysis).where(Analysis.customer.ilike(f"%{customer_name[:50]}%"))
    result = await session.execute(stmt)
    analyses = result.scalars().all()

    if not analyses:
        return {
            "customer": customer_name,
            "trust_score": 50.0,
            "trust_label": "no_data",
            "total_lots": 0,
            "source": "local_db",
            "is_estimate": True,
            "evidence_count": 0,
            "method": "internal_analyses",
            "disclaimer": "Внутренних анализов по заказчику пока нет; надёжность не проверена.",
        }

    # Простая эвристика: чем больше анализов по заказчику, тем надёжнее
    total = len(analyses)
    avg_risk = (
        sum(
            {"low": 0, "medium": 1, "high": 2, "needs_review": 1}.get(a.overall_risk, 1)
            for a in analyses
        )
        / total
    )

    # Обратный риск: high risk = низкий trust
    base_score = 80.0 - (avg_risk * 20.0)

    # Бонус за объём: больше 5 лотов = +5, больше 20 = +10
    if total > 20:
        base_score += 10
    elif total > 5:
        base_score += 5

    trust_score = max(0, min(100, base_score))

    if trust_score >= 70:
        label = "trusted"
    elif trust_score >= 50:
        label = "neutral"
    elif trust_score >= 30:
        label = "risky"
    else:
        label = "avoid"

    return {
        "customer": customer_name,
        "trust_score": round(trust_score, 1),
        "trust_label": label,
        "total_lots": total,
        "avg_risk": ("low" if avg_risk < 0.5 else "medium" if avg_risk < 1.5 else "high"),
        "source": "local_db",
        "is_estimate": True,
        "evidence_count": total,
        "method": "internal_analyses",
        "disclaimer": (
            f"Оценка рассчитана только по {total} внутренним анализам Tendr "
            "и не подтверждает платёжную дисциплину или надёжность заказчика."
        ),
    }


def add_score_to_analysis(
    analysis: dict[str, Any], score: dict[str, Any], margin: dict[str, Any]
) -> dict[str, Any]:
    """Дополнить ответ анализа скорингом и маржинальностью."""
    if "lot" not in analysis:
        return analysis
    # Кладём в extra, чтобы не ломать существующую схему
    analysis["lot"]["_score"] = score
    analysis["lot"]["_margin"] = margin
    return analysis
