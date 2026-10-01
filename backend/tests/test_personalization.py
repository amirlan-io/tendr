"""Тесты персонализации: профиль пользователя (F7) и подбор тендеров (F8).

Критерий приёмки F8: у каждой рекомендации есть объяснение «почему»,
а не голый процент. Проверяем именно это.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.outreach_agent import CompanyContacts
from app.services.personalization import (
    CompanyContext,
    TenderInterest,
    adjust_weights_from_feedback,
    build_company_block,
    build_outreach_signature,
    build_search_prompt_context,
    confidence_label,
    contacts_from_profile,
    rank_tenders,
    score_tender,
)

# ── F7: профиль компании ─────────────────────────────────────────────


def test_company_block_lists_categories_and_regions() -> None:
    ctx = CompanyContext(
        categories=["фильтры", "вентиляция"],
        regions=["Астана"],
        contacts=CompanyContacts(company_name="ТОО Ромашка", contact_name="Иван"),
    )
    block = build_company_block(ctx)
    assert "фильтры" in block
    assert "Астана" in block
    assert "ТОО Ромашка" in block


def test_company_block_empty_when_no_profile() -> None:
    assert build_company_block(CompanyContext()) == ""


def test_search_context_excludes_contacts_for_privacy() -> None:
    """F7: контакты не должны попадать в промпты поиска (приватность)."""
    ctx = CompanyContext(
        categories=["фильтры"],
        contacts=CompanyContacts(work_email="boss@romashka.kz", work_phone="+7 701 000 00 00"),
    )
    search_ctx = build_search_prompt_context(ctx)
    assert "boss@romashka.kz" not in search_ctx
    assert "+7 701 000 00 00" not in search_ctx


def test_outreach_signature_includes_contacts() -> None:
    """А в исходящих материалах контакты НУЖНЫ."""
    ctx = CompanyContext(
        contacts=CompanyContacts(
            contact_name="Иван", company_name="ТОО Ромашка",
            work_email="boss@romashka.kz", work_phone="+7 701 000 00 00",
        )
    )
    sig = build_outreach_signature(ctx)
    assert "boss@romashka.kz" in sig
    assert "Иван" in sig


def test_contacts_from_profile_extracts_fields() -> None:
    class FakeProfile:
        contact_name = "Иван"
        company_name = "ТОО Ромашка"
        work_email = "boss@romashka.kz"
        work_phone = "+7 701 000 00 00"

    contacts = contacts_from_profile(FakeProfile())
    assert contacts.contact_name == "Иван"
    assert contacts.work_email == "boss@romashka.kz"


def test_contacts_from_none_profile_is_empty() -> None:
    contacts = contacts_from_profile(None)
    assert contacts.contact_name == ""
    assert contacts.work_email == ""


# ── F8: скоринг тендеров ─────────────────────────────────────────────


def _lot(**overrides):
    base = {
        "lot_id": "1001",
        "title": "Поставка фильтров для вентиляции",
        "description": "Фильтрующие элементы",
        "category": "фильтры",
        "region": "Астана",
        "customer": "Акимат Астаны",
        "amount_kzt": 500_000.0,
        "is_urgent": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


def test_matching_lot_gets_high_score_with_reasons() -> None:
    interest = TenderInterest(
        categories=["фильтры"], regions=["Астана"],
        min_budget_kzt=100_000.0, max_budget_kzt=1_000_000.0, quiz_completed=True,
    )
    scored = score_tender(_lot(), interest)
    assert scored.score >= 60
    assert scored.reasons, "рекомендация обязана объясняться"
    assert len(scored.reasons) <= 3


def test_irrelevant_lot_scores_low() -> None:
    interest = TenderInterest(categories=["фильтры"], regions=["Астана"], max_budget_kzt=1_000_000.0)
    scored = score_tender(
        _lot(title="Поставка офисной мебели", category="мебель", region="Алматы"),
        interest,
    )
    assert scored.score < 30


def test_explanation_mentions_concrete_reason() -> None:
    interest = TenderInterest(categories=["фильтры"], max_budget_kzt=1_000_000.0)
    scored = score_tender(_lot(), interest)
    joined = " ".join(scored.reasons)
    assert "фильтр" in joined.lower() or "бюджет" in joined.lower()


def test_urgent_lot_gets_urgency_bonus() -> None:
    interest = TenderInterest(categories=["фильтры"], max_budget_kzt=1_000_000.0)
    normal = score_tender(_lot(is_urgent=False), interest)
    urgent = score_tender(_lot(is_urgent=True), interest)
    assert urgent.score > normal.score


def test_fresh_lot_scores_higher_than_old() -> None:
    interest = TenderInterest(categories=["фильтры"], max_budget_kzt=1_000_000.0)
    now = datetime.now(UTC)
    fresh = score_tender(_lot(created_at=now.isoformat()), interest, now=now)
    old = score_tender(_lot(created_at=(now - timedelta(days=60)).isoformat()), interest, now=now)
    assert fresh.score >= old.score


def test_rank_tenders_sorts_by_score_desc() -> None:
    interest = TenderInterest(categories=["фильтры"], regions=["Астана"], max_budget_kzt=1_000_000.0)
    lots = [
        _lot(lot_id="a", title="Мебель", category="мебель", region="Алматы"),
        _lot(lot_id="b", title="Фильтры", category="фильтры", region="Астана"),
    ]
    ranked = rank_tenders(lots, interest, limit=5)
    assert ranked[0].lot_id == "b"
    scores = [t.score for t in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_tenders_respects_min_score() -> None:
    interest = TenderInterest(categories=["фильтры"])
    lots = [_lot(lot_id="z", title="Совсем другое", category="книги")]
    assert rank_tenders(lots, interest, min_score=30) == []


def test_rank_tenders_empty_input() -> None:
    assert rank_tenders([], TenderInterest()) == []


def test_cold_start_profile_still_returns_something() -> None:
    """Даже без квиза лот с совпадением по категории должен попасть в выдачу."""
    interest = TenderInterest(categories=["фильтры"], quiz_completed=False)
    ranked = rank_tenders([_lot()], interest, min_score=10)
    assert len(ranked) == 1


def test_confidence_labels_are_honest() -> None:
    assert confidence_label(85) == "высокое совпадение"
    assert confidence_label(5) == "подходит слабо"


def test_adjust_weights_noop_with_insufficient_feedback() -> None:
    base = {"w": 10.0}
    assert adjust_weights_from_feedback(base, fits=2, not_fits=2) == base


def test_adjust_weights_shifts_toward_positive_feedback() -> None:
    base = {"w": 10.0}
    up = adjust_weights_from_feedback(base, fits=10, not_fits=0)
    down = adjust_weights_from_feedback(base, fits=0, not_fits=10)
    assert up["w"] > base["w"]
    assert down["w"] < base["w"]