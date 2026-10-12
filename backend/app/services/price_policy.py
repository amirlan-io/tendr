"""Политика торга по цене (F6 ТЗ).

Ключевой инвариант проекта: агент НЕ принимает коммерческих обязательств.
Здесь это закодировано состояниями, а не текстом промпта — модель не может
«договориться», потому что у неё просто нет такого инструмента.

Шкала (отклонение цены от базовой, %):
    <= tolerance_pct (X)      → ACCEPT      — принимаем, идём дальше
    <= counter_limit_pct (Y)  → COUNTER_ONCE — ровно одна встречная попытка
    >  counter_limit_pct (Y)  → DECLINE      — вежливый отказ без обязательств

Повторная встречачная попытка невозможна: переход COUNTER_ONCE терминальный,
после него только DECLINE. Это и есть защита от «затяжного торга».
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any


class PriceAction(str, Enum):
    """Действие агента по итогам переговоров о цене."""

    ACCEPT = "accept"
    COUNTER_ONCE = "counter_once"
    DECLINE = "decline"


class PriceOutcome(str, Enum):
    """Итог, который записывается в outreach_jobs.price_outcome."""

    ACCEPTED = "accepted"
    COUNTERED = "countered"
    DECLINED = "declined"


#: Отказы, при которых обязательства не возникают — используются в текстах.
DECLINE_REASONS: dict[str, str] = {
    "over_limit": "Цена превышает допустимый порог, отказались без обязательств.",
    "already_countered": "Встречная попытка уже использована, дальнейший торг не ведём.",
    "counter_outcome_worse": "Встречное предложение отклонено поставщиком.",
}


def default_tolerance_pct() -> float:
    return 5.0


def default_counter_limit_pct() -> float:
    return 15.0


def normalize_pct(value: Any, *, default: float) -> float:
    """Привести процент к безопасному диапазону 0..100."""
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(pct):
        return default
    return max(0.0, min(100.0, pct))


def deviation_pct(price: float, reference: float) -> float | None:
    """Отклонение цены от базовой в процентах (по модулю).

    ``reference`` — базовая цена: бюджет лота, заявленная цена или прошлая
    скидка. Возвращает ``None``, если базы нет (тогда сравнивать не с чем и
    решение принимает пользователь).
    """
    try:
        price = float(price)
        reference = float(reference)
    except (TypeError, ValueError):
        return None
    if reference <= 0:
        return None
    return abs(price - reference) / reference * 100.0


def decide_price_action(
    price: float,
    reference: float,
    *,
    tolerance_pct: float = default_tolerance_pct(),
    counter_limit_pct: float = default_counter_limit_pct(),
    counter_used: bool = False,
) -> tuple[PriceAction, float | None]:
    """Определить действие агента по цене.

    Возвращает ``(action, deviation)``. Правила:

    * нет базовой цены → ``COUNTER_ONCE`` (просим уточнить), если уже не
      торговались, иначе ``DECLINE``;
    * отклонение <= X → ``ACCEPT``;
    * отклонение <= Y → ``COUNTER_ONCE`` (одна попытка);
    * отклонение > Y → ``DECLINE``;
    * встречная уже была → ``DECLINE`` независимо от суммы.

    Это чистая функция: её поведение полностью покрывается тестами, а агент
    лишь исполняет возвращённое решение.
    """
    tol = normalize_pct(tolerance_pct, default=default_tolerance_pct())
    limit = normalize_pct(counter_limit_pct, default=default_counter_limit_pct())
    # Y не может быть меньше X — иначе «зона встречной» исчезает.
    limit = max(limit, tol)

    deviation = deviation_pct(price, reference)

    if deviation is None:
        # Нет базы для сравнения: одна попытка уточнить, дальше — стоп.
        return (PriceAction.DECLINE if counter_used else PriceAction.COUNTER_ONCE), None

    if counter_used:
        # Торг исчерпан в любую сторону.
        return PriceAction.DECLINE, deviation

    if deviation <= tol:
        return PriceAction.ACCEPT, deviation
    if deviation <= limit:
        return PriceAction.COUNTER_ONCE, deviation
    return PriceAction.DECLINE, deviation


def apply_counter(action: PriceAction, counter_accepted: bool) -> PriceOutcome:
    """Перевести результат встречной попытки в исход.

    ``counter_accepted=True`` означает, что поставщик принял встречную цену;
    тогда исход — ``ACCEPTED``. Иначе — ``DECLINED``: обязательств не возникло.
    """
    if action is PriceAction.ACCEPT:
        return PriceOutcome.ACCEPTED
    if action is PriceAction.COUNTER_ONCE:
        return PriceOutcome.ACCEPTED if counter_accepted else PriceOutcome.DECLINED
    return PriceOutcome.DECLINED


def decline_text(reason: str = "over_limit", *, counter_script: str | None = None) -> str:
    """Текст отказа/паузы без коммерческих обязательств."""
    base = DECLINE_REASONS.get(reason, DECLINE_REASONS["over_limit"])
    if reason == "already_countered":
        return base
    if reason == "counter_outcome_worse":
        return base
    if counter_script:
        return f"{base} Ответ по вашему предложению: {counter_script.strip()}"
    return base


def counter_text(counter_script: str | None = None) -> str:
    """Текст единственной встречной попытки."""
    if counter_script and counter_script.strip():
        return counter_script.strip()
    return (
        "К сожалению, предложенная цена выше нашего бюджета. "
        "Возможна ли корректировка в меньшую сторону?"
    )


def agent_toolset() -> frozenset[str]:
    """Инструменты, доступные агенту переговоров.

    Здесь намеренно НЕТ операций «accept_price», «sign_contract», «pay».
    Их отсутствие в наборе — архитектурная гарантия F6, а не запрет в тексте.
    """
    return frozenset(
        {
            "search_suppliers",
            "read_supplier_page",
            "compare_requirements",
            "draft_email",
            "draft_call_plan",
            "collect_contacts",
        }
    )


FORBIDDEN_AGENT_TOOLS: frozenset[str] = frozenset(
    {
        "accept_price",
        "sign_contract",
        "place_order",
        "pay_invoice",
        "send_email_unapproved",
        "place_call_unapproved",
    }
)