"""Персонализация: системный промпт пользователя (F7) и подбор тендеров (F8).

F7 — системный промпт агента собирается из шаблона + профиля компании +
рабочих контактов. Контакты попадают ТОЛЬКО в исходящие материалы; в промпт
поиска они не подставляются, чтобы не утекать в Tavily/LLM-запросы.

F8 — «подобрано для вас»: скоринг v1 (без ML) считается поверх существующего
поиска лотов. Каждая рекомендация объясняется тремя буллетами, а не голым
процентом — это и есть отличие от конкурентов.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.agents.outreach_agent import CompanyContacts

# ── F7: персональный контекст агента ───────────────────────────────────


@dataclass(slots=True)
class CompanyContext:
    """Профиль компании, из которого собирается персонализация."""

    categories: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    capabilities: str = ""
    min_check_kzt: float | None = None
    budget_max_kzt: float | None = None
    contacts: CompanyContacts = field(default_factory=CompanyContacts)

    @property
    def is_empty(self) -> bool:
        return not (
            self.categories or self.regions or self.capabilities
            or self.min_check_kzt or self.budget_max_kzt
        )


def contacts_from_profile(profile: Any) -> CompanyContacts:
    """Достать рабочие контакты из строки company_profiles."""
    if profile is None:
        return CompanyContacts()
    return CompanyContacts(
        contact_name=str(getattr(profile, "contact_name", "") or "")[:128],
        company_name=str(getattr(profile, "company_name", "") or "")[:255],
        work_email=str(getattr(profile, "work_email", "") or "")[:255],
        work_phone=str(getattr(profile, "work_phone", "") or "")[:32],
    )


def build_company_block(context: CompanyContext) -> str:
    """Человекочитаемый блок «кто мы» для промпта агента."""
    lines = ["Кто заказчик (компания пользователя):"]
    if context.contacts.company_name:
        lines.append(f"- Компания: {context.contacts.company_name}")
    if context.contacts.contact_name:
        lines.append(f"- Контактное лицо: {context.contacts.contact_name}")
    if context.categories:
        lines.append(f"- Категории поставок: {', '.join(context.categories[:10])}")
    if context.regions:
        lines.append(f"- Регионы работы: {', '.join(context.regions[:10])}")
    if context.capabilities:
        lines.append(f"- Возможности: {context.capabilities[:800]}")
    if context.min_check_kzt:
        lines.append(f"- Минимальный чек: {context.min_check_kzt:.0f} тг")
    if context.budget_max_kzt:
        lines.append(f"- Максимальный бюджет: {context.budget_max_kzt:.0f} тг")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_outreach_signature(context: CompanyContext) -> str:
    """Подпись для исходящих писем/сценариев. Только здесь нужны контакты."""
    lines = context.contacts.signature_lines()
    return "\n".join(lines)


def build_search_prompt_context(context: CompanyContext) -> str:
    """Контекст для ПОИСКА — без контактов (приватность).

    Контакты не должны попадать в промпты, которые уходят в LLM/Tavily:
    это личные данные пользователя, не нужные для поиска поставщика.
    """
    return build_company_block(context)


# ── F8: подбор тендеров ────────────────────────────────────────────────


@dataclass(slots=True)
class TenderInterest:
    """Интересы пользователя для скоринга (из квиза + поведения)."""

    categories: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    min_budget_kzt: float | None = None
    max_budget_kzt: float | None = None
    # Минимальный чек компании: лоты дешевле — неинтересны.
    min_check_kzt: float | None = None
    quiz_completed: bool = False
    known_customers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScoredTender:
    """Тендер с баллом и объяснением «почему»."""

    lot_id: str
    title: str
    score: int
    reasons: list[str] = field(default_factory=list)
    is_urgent: bool = False
    deadline_date: str | None = None
    amount_kzt: float | None = None
    customer: str = ""
    category: str = ""
    region: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lot_id": self.lot_id,
            "title": self.title,
            "score": self.score,
            "reasons": self.reasons[:3],
            "is_urgent": self.is_urgent,
            "deadline_date": self.deadline_date,
            "amount_kzt": self.amount_kzt,
            "customer": self.customer,
        }


# Веса скоринга v1. Подобраны так, чтобы объяснение «почему» получалось
# осмысленным: три верхних фактора дают основной балл.
W_CATEGORY = 30.0
W_REGION = 18.0
W_BUDGET = 16.0
W_KEYWORD = 14.0
W_CUSTOMER = 12.0
W_FRESHNESS = 8.0
W_URGENCY = 6.0
MAX_SCORE = 100.0


def _norm(text: str | None) -> str:
    return str(text or "").strip().lower()


def _contains_any(haystack: str, needles: Sequence[str]) -> bool:
    low = _norm(haystack)
    return any(_norm(n) and _norm(n) in low for n in needles)


def _freshness_score(created_at: Any, now: datetime | None = None) -> float:
    """Свежесть: 0 при старше 30 дней, полная при свежем."""
    moment = now or datetime.now(UTC)
    if created_at is None:
        return 0.0
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.removesuffix("Z") + "+00:00")
        except ValueError:
            return 0.0
    if not isinstance(created_at, datetime):
        return 0.0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max(0.0, (moment - created_at.astimezone(UTC)).total_seconds() / 86400.0)
    if age_days >= 30:
        return 0.0
    return max(0.0, 1.0 - age_days / 30.0)


def score_tender(
    lot: dict[str, Any],
    interest: TenderInterest,
    *,
    now: datetime | None = None,
) -> ScoredTender:
    """Скоринг одного лота. Возвращает балл и до трёх причин.

    Без объяснения нельзя: UI показывает «почему», а не процент (F8).
    """
    title = str(lot.get("title") or "")
    category = str(lot.get("category") or "")
    region = str(lot.get("region") or "")
    customer = str(lot.get("customer") or lot.get("organizer") or "")
    description = str(lot.get("description") or "")
    amount = lot.get("amount_kzt") or lot.get("budget_kzt")
    try:
        amount_val = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_val = None

    score = 0.0
    reasons: list[tuple[float, str]] = []

    if interest.categories and _contains_any(category, interest.categories):
        score += W_CATEGORY
        reasons.append((W_CATEGORY, f"Категория «{category}» совпадает с вашим профилем"))
    elif interest.categories and _contains_any(title + " " + description, interest.categories):
        score += W_CATEGORY * 0.5
        reasons.append((W_CATEGORY * 0.5, "Похоже на ваши категории по названию/описанию"))

    if interest.regions and region and _contains_any(region, interest.regions):
        score += W_REGION
        reasons.append((W_REGION, f"Регион «{region}» входит в ваши регионы"))

    if amount_val is not None:
        if interest.max_budget_kzt and amount_val <= float(interest.max_budget_kzt):
            score += W_BUDGET
            reasons.append((W_BUDGET, "Бюджет лота укладывается в ваш лимит"))
        if interest.min_check_kzt and amount_val >= float(interest.min_check_kzt):
            score += W_BUDGET * 0.5
            reasons.append((W_BUDGET * 0.5, "Сумма выше вашего минимального чека"))

    if interest.keywords and _contains_any(title, interest.keywords):
        score += W_KEYWORD
        reasons.append((W_KEYWORD, "Совпадение по ключевым словам"))

    if interest.known_customers and customer and _contains_any(customer, interest.known_customers):
        score += W_CUSTOMER
        reasons.append((W_CUSTOMER, f"Знакомый заказчик: {customer[:80]}"))

    freshness = _freshness_score(lot.get("created_at"), now)
    if freshness > 0:
        score += W_FRESHNESS * freshness
        reasons.append((W_FRESHNESS * freshness, "Свежая закупка"))

    if lot.get("is_urgent"):
        score += W_URGENCY
        reasons.append((W_URGENCY, "Горит дедлайн — быстрое решение"))

    final = round(min(score, MAX_SCORE))
    reasons.sort(key=lambda r: r[0], reverse=True)
    return ScoredTender(
        lot_id=str(lot.get("lot_id") or lot.get("id") or ""),
        title=title[:512],
        score=final,
        reasons=[text for _, text in reasons[:3]],
        is_urgent=bool(lot.get("is_urgent")),
        deadline_date=lot.get("deadline_date"),
        amount_kzt=amount_val,
        customer=customer[:512],
        category=category[:128],
        region=region[:128],
    )


def rank_tenders(
    lots: Sequence[dict[str, Any]],
    interest: TenderInterest,
    *,
    limit: int = 10,
    min_score: int = 10,
    now: datetime | None = None,
) -> list[ScoredTender]:
    """Отсортировать лоты по релевантности и оставить лучшие."""
    scored = [score_tender(lot, interest, now=now) for lot in lots]
    scored = [t for t in scored if t.score >= min_score]
    scored.sort(key=lambda t: (t.score, t.is_urgent), reverse=True)
    return scored[: max(1, limit)]


def adjust_weights_from_feedback(
    base_weights: dict[str, float],
    *,
    fits: int,
    not_fits: int,
    lr: float = 0.15,
) -> dict[str, float]:
    """Скоринг v2-заготовка: слегка сдвинуть веса по сигналу фидбека.

    Намеренно простое и прозрачное — без ML. Работает, когда фидбека мало,
    и не переобучается, потому что шаг ограничен.
    """
    if fits + not_fits < 5:
        return dict(base_weights)
    ratio = (fits + 1) / (fits + not_fits + 2)  # сглаживание Лапласа
    factor = 1.0 + lr * (ratio - 0.5)
    return {key: max(1.0, min(60.0, value * factor)) for key, value in base_weights.items()}


def confidence_label(score: int) -> str:
    """Подпись к баллу — чтобы не пугать точностью."""
    if score >= 70:
        return "высокое совпадение"
    if score >= 45:
        return "среднее совпадение"
    if score >= 20:
        return "слабое совпадение"
    return "подходит слабо"


def next_digest_time(hour_kz: int, now: datetime | None = None) -> datetime:
    """Следующее время отправки дайджеста по Алматы."""
    from zoneinfo import ZoneInfo

    kz = ZoneInfo("Asia/Almaty")
    moment = now.astimezone(kz) if now and now.tzinfo else datetime.now(kz)
    target = moment.replace(hour=max(0, min(23, int(hour_kz))), minute=0, second=0, microsecond=0)
    if target <= moment:
        target = target.replace(day=target.day) + __import__("datetime").timedelta(days=1)
    return target


def clamp(value: float, low: float, high: float) -> float:
    """Ограничить значение (используется в нормализации весов)."""
    return max(low, min(high, value))


def softmax_weights(scores: Sequence[float]) -> list[float]:
    """Нормализация набора баллов в веса (для будущих объяснений)."""
    if not scores:
        return []
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]
    total = sum(exps) or 1.0
    return [e / total for e in exps]