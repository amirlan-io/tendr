"""Тесты Supplier Agent по критериям приёмки ТЗ §10.

Особое внимание — инвариантам безопасности:
* без approval ноль исходящих действий;
* агент не может принять цену или заключить договор (нет инструментов);
* политика торга: превышение предела → отказ без обязательств.

Внешние сети (Tavily, Browser-Use, LLM) не вызываются: агент тестируется
через детерминированные чистые функции.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agents.outreach_agent import effective_mode as outreach_effective_mode
from app.agents.outreach_agent import (
    find_forbidden_phrase,
    has_stop_word,
    is_working_hours_kz,
    normalize_mode,
    sanitize_draft,
    validate_draft_for_send,
)
from app.agents.supplier_agent import (
    MATCH_FITS,
    MATCH_NO,
    MATCH_PARTIAL,
    MATCH_UNKNOWN,
    Requirement,
    SupplierCandidate,
    build_warnings,
    dedupe_requirements,
    extract_domain,
    find_contacts,
    normalize_match_status,
    score_from_matches,
)
from app.services.price_policy import (
    FORBIDDEN_AGENT_TOOLS,
    PriceAction,
    PriceOutcome,
    agent_toolset,
    apply_counter,
    decide_price_action,
    deviation_pct,
)

KZ = ZoneInfo("Asia/Almaty")


# ── F6: политика торга закодирована состояниями ─────────────────────────


def test_price_within_tolerance_is_accepted() -> None:
    action, dev = decide_price_action(105.0, 100.0, tolerance_pct=5.0)
    assert action is PriceAction.ACCEPT
    assert dev == pytest.approx(5.0)


def test_price_above_tolerance_allows_single_counter() -> None:
    action, dev = decide_price_action(110.0, 100.0, tolerance_pct=5.0, counter_limit_pct=15.0)
    assert action is PriceAction.COUNTER_ONCE
    assert dev == pytest.approx(10.0)


def test_price_beyond_limit_is_declined_without_obligations() -> None:
    action, dev = decide_price_action(150.0, 100.0, tolerance_pct=5.0, counter_limit_pct=15.0)
    assert action is PriceAction.DECLINE
    assert dev == pytest.approx(50.0)


def test_counter_is_one_shot_only() -> None:
    """После встречной попытки дальнейший торг невозможен (F6)."""
    action, _ = decide_price_action(101.0, 100.0, tolerance_pct=5.0, counter_used=True)
    assert action is PriceAction.DECLINE


def test_counter_accepted_yields_accepted_outcome() -> None:
    assert apply_counter(PriceAction.COUNTER_ONCE, counter_accepted=True) is PriceOutcome.ACCEPTED


def test_counter_rejected_yields_declined_outcome() -> None:
    assert apply_counter(PriceAction.COUNTER_ONCE, counter_accepted=False) is PriceOutcome.DECLINED


def test_decline_never_yields_accepted_outcome() -> None:
    assert apply_counter(PriceAction.DECLINE, counter_accepted=True) is PriceOutcome.DECLINED


def test_missing_reference_price_goes_to_counter_then_stops() -> None:
    """Нет базы для сравнения — одна попытка уточнить, дальше стоп."""
    action, dev = decide_price_action(123.0, 0.0)
    assert action is PriceAction.COUNTER_ONCE
    assert dev is None
    action2, _ = decide_price_action(123.0, 0.0, counter_used=True)
    assert action2 is PriceAction.DECLINE


def test_counter_limit_below_tolerance_is_clamped() -> None:
    """Y < X недопустим — зона встречной не должна исчезнуть."""
    action, _ = decide_price_action(110.0, 100.0, tolerance_pct=20.0, counter_limit_pct=5.0)
    assert action is PriceAction.ACCEPT


def test_agent_has_no_commercial_tools() -> None:
    """У агента нет инструментов «согласиться/подписать/оплатить» (F6)."""
    tools = agent_toolset()
    assert tools & FORBIDDEN_AGENT_TOOLS == frozenset()
    for forbidden in ("accept_price", "sign_contract", "pay_invoice"):
        assert forbidden not in tools


def test_deviation_pct_handles_zero_reference() -> None:
    assert deviation_pct(100.0, 0.0) is None


# ── F1: извлечение домена и контактов ─────────────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.kaspi.kz/shop/", "kaspi.kz"),
        ("https://sulpak.kz/x", "sulpak.kz"),
        ("not-a-url", ""),
    ],
)
def test_extract_domain(url: str, expected: str) -> None:
    assert extract_domain(url) == expected


def test_find_contacts_returns_explicit_matches_only() -> None:
    text = "Позвоните: +7 727 123 45 67 или пишите sales@example.kz"
    email, phone = find_contacts(text)
    assert email == "sales@example.kz"
    assert phone  # телефон найден явно


def test_find_contacts_returns_empty_when_absent() -> None:
    email, phone = find_contacts("Цены в магазине, доставка бесплатно.")
    assert email == "" and phone == ""


def test_find_contacts_rejects_image_like_email() -> None:
    email, _ = find_contacts("logo@site.png")
    assert email == ""


# ── F2: сверка по пунктам ТЗ ──────────────────────────────────────────


def test_match_status_normalization_handles_russian_aliases() -> None:
    assert normalize_match_status("подходит") == MATCH_FITS
    assert normalize_match_status("частично") == MATCH_PARTIAL
    assert normalize_match_status("не подходит") == MATCH_NO
    assert normalize_match_status("нет данных") == MATCH_UNKNOWN
    assert normalize_match_status("мусор") == MATCH_UNKNOWN


def test_score_from_matches_weights_partial_and_unknown() -> None:
    score = score_from_matches(
        [{"status": MATCH_FITS}, {"status": MATCH_PARTIAL}, {"status": MATCH_UNKNOWN}]
    )
    assert 0 < score < 100


def test_score_from_matches_zero_when_no_matches() -> None:
    assert score_from_matches([]) == 0


def test_dedupe_requirements_removes_duplicates() -> None:
    reqs = dedupe_requirements(
        [
            {"code": "1", "title": "Сталь 304"},
            {"code": "2", "title": "сталь 304"},  # регистр/пробел → дубль
            {"code": "3", "title": ""},  # пустое → выкинуть
        ]
    )
    assert len(reqs) == 1
    assert reqs[0].title == "Сталь 304"


def test_build_warnings_flags_missing_certificates_and_contacts() -> None:
    candidate = SupplierCandidate(supplier="X", domain="x.kz", title="T")
    candidate.requirement_matches = [{"code": "1", "status": MATCH_FITS}]
    warnings = build_warnings(candidate, [Requirement(code="1", title="Req", is_mandatory=True)])
    joined = " ".join(warnings)
    assert "Сертификаты" in joined
    assert "Гарантия" in joined
    assert "Контакты" in joined


def test_build_warnings_flags_middleman() -> None:
    candidate = SupplierCandidate(
        supplier="X", domain="olx.kz", title="T", is_middleman=True,
        email="a@b.kz", phone="+7 700 000 00 00", certificates=["ISO"], warranty="12 мес",
    )
    candidate.requirement_matches = [{"code": "1", "status": MATCH_FITS}]
    warnings = build_warnings(candidate, [Requirement(code="1", title="Req")])
    assert any("посредник" in w.lower() for w in warnings)


# ── F4: режимы отправки ───────────────────────────────────────────────


def test_manual_mode_blocks_sending() -> None:
    assert normalize_mode("manual") == "manual"
    # Даже trusted при стоп-листе/лимите понижается, но manual остаётся manual.
    assert outreach_effective_mode("manual", blocked=True) == "manual"


def test_trusted_mode_downgrades_to_review_on_block() -> None:
    assert outreach_effective_mode("trusted", blocked=True) == "review"


def test_trusted_mode_downgrades_to_review_on_daily_limit() -> None:
    assert outreach_effective_mode("trusted", blocked=False, daily_sent=5, daily_limit=5) == "review"


def test_unknown_mode_defaults_to_review() -> None:
    assert normalize_mode("что-то") == "review"


def test_stop_words_detected() -> None:
    assert has_stop_word("готов подписать договор") == "договор"
    assert has_stop_word("просто вопрос") is None


def test_sanitize_draft_removes_commitment_phrases() -> None:
    cleaned = sanitize_draft("Мы принимаем ваши условия и готовы обсудить сроки.")
    assert "принимаем ваши условия" not in cleaned.lower()


def test_forbidden_phrase_detected() -> None:
    assert find_forbidden_phrase("мы подписываем договор") is not None


def test_validate_draft_blocks_obligations() -> None:
    ok, reason = validate_draft_for_send(
        {"ok": True, "body": "мы принимаем ваши условия", "blocked_phrase": "мы принимаем ваши условия"}
    )
    assert ok is False
    assert reason == "DRAFT_HAS_OBLIGATION"


def test_validate_draft_blocks_empty() -> None:
    ok, reason = validate_draft_for_send({"ok": True, "body": "  "})
    assert ok is False and reason == "DRAFT_EMPTY"


def test_validate_draft_passes_clean() -> None:
    ok, reason = validate_draft_for_send({"ok": True, "body": "Здравствуйте, интересует поставка."})
    assert ok is True and reason is None


# ── F5: рабочее время Казахстана ─────────────────────────────────────


def test_working_hours_weekday() -> None:
    # Среда, 12:00 по Алматы
    wednesday = datetime(2026, 10, 7, 12, 0, tzinfo=KZ)
    assert is_working_hours_kz(wednesday) is True


def test_outside_working_hours_evening() -> None:
    evening = datetime(2026, 10, 7, 21, 0, tzinfo=KZ)
    assert is_working_hours_kz(evening) is False


def test_outside_working_hours_weekend() -> None:
    saturday = datetime(2026, 10, 10, 12, 0, tzinfo=KZ)  # суббота
    assert is_working_hours_kz(saturday) is False