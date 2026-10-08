"""Тесты канала пересылки ошибок.

Главная проверка — что в уведомление не утекают секреты и контакты.
Ошибка это диагностика, а не дамп данных клиента.
"""

from __future__ import annotations

import pytest

from app.services.error_reporter import (
    RATE_LIMIT_PER_HOUR,
    ErrorReporter,
    fingerprint,
    scrub,
    scrub_payload,
)

# ── Вычистка секретов ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,must_hide",
    [
        ("ключ bu_abcdefghijklmnopqrstuvwxyz123456", "bu_abcdefghijklmnopqrstuvwxyz123456"),
        ("Tavily tvly-abcdefghijklmnop12345", "tvly-abcdefghijklmnop12345"),
        ("токен eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefgh", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefgh"),
        ("OpenAI sk-abcdefghijklmnopqrstuv", "sk-abcdefghijklmnopqrstuv"),
        ("телефон +7 727 123 45 67", "727 123 45 67"),
        ("почта sales@company.kz", "sales@company.kz"),
    ],
)
def test_secrets_are_scrubbed(raw: str, must_hide: str) -> None:
    cleaned = scrub(raw)
    assert must_hide not in cleaned
    assert "[скрыто]" in cleaned


def test_scrub_handles_empty_and_long() -> None:
    assert scrub(None) == ""
    assert scrub("") == ""
    assert len(scrub("A" * 5000)) <= 1200


def test_sensitive_keys_are_masked() -> None:
    payload = scrub_payload(
        {
            "api_key": "что-то",
            "password": "что-то",
            "user_email": "a@b.kz",
            "lot_title": "Поставка фильтров",
            "nested": {"token": "что-то", "count": 5, "ok": True},
        }
    )
    assert payload["api_key"] == "[скрыто]"
    assert payload["password"] == "[скрыто]"
    assert payload["user_email"] == "[скрыто]"
    # Нейтральные данные остаются — они полезны для диагностики
    assert payload["lot_title"] == "Поставка фильтров"
    assert payload["nested"]["token"] == "[скрыто]"
    assert payload["nested"]["count"] == 5


def test_scrub_payload_limits_size() -> None:
    payload = scrub_payload({"items": list(range(100))})
    assert len(payload["items"]) <= 20
    deep: dict = {}
    node = deep
    for _ in range(10):
        node["n"] = {}
        node = node["n"]
    # Глубокая вложенность обрезается, а не уходит в бесконечную рекурсию
    scrub_payload(deep)


# ── Дедупликация ───────────────────────────────────────────────────────


def test_fingerprint_is_stable_and_distinct() -> None:
    a = fingerprint("TypeError", "boom", "POST /api/x")
    b = fingerprint("TypeError", "boom", "POST /api/x")
    c = fingerprint("TypeError", "boom", "POST /api/y")
    assert a == b
    assert a != c


def test_identical_errors_are_suppressed() -> None:
    reporter = ErrorReporter(bot_token="", admin_ids=[])
    key = "same"
    assert reporter._should_send(key) is True
    # Повтор в пределах окна подавляется — иначе петля завалит Telegram
    assert reporter._should_send(key) is False


def test_rate_limit_caps_flood() -> None:
    reporter = ErrorReporter(bot_token="", admin_ids=[])
    sent = sum(1 for i in range(RATE_LIMIT_PER_HOUR + 15) if reporter._should_send(f"e{i}"))
    assert sent == RATE_LIMIT_PER_HOUR


def test_old_entries_expire(monkeypatch) -> None:
    monkeypatch.setattr("app.services.error_reporter.time.monotonic", lambda: 7200.0)
    reporter = ErrorReporter(bot_token="", admin_ids=[])
    reporter._seen["old"] = 0.0  # очень давно по monotonic-шкале
    reporter._sent_times = [0.0]
    # Старое забывается, новое проходит
    assert reporter._should_send("old") is True


# ── Формат сообщения ───────────────────────────────────────────────────


def test_message_contains_context_and_no_secrets() -> None:
    reporter = ErrorReporter(bot_token="bu_x", admin_ids=[1], app_env="prod")
    text = reporter.format_message(
        {
            "source": "backend",
            "name": "ApiError",
            "message": "ошибка с ключом bu_abcdefghijklmnopqrstuvwxyz",
            "where": "POST /api/lots/analyze",
            "user_hint": "tester@example.com",
            "stack": "Traceback ... bu_abcdefghijklmnopqrstuvwxyz",
        }
    )
    assert "ApiError" in text
    assert "/api/lots/analyze" in text
    assert "prod" in text
    assert "bu_abcdefghijklmnopqrstuvwxyz" not in text
    assert "tester@example.com" not in text


def test_message_fits_telegram_limit() -> None:
    reporter = ErrorReporter(bot_token="bu_x", admin_ids=[1])
    text = reporter.format_message(
        {"message": "A" * 5000, "stack": "B" * 5000, "name": "N" * 500}
    )
    assert len(text) <= 3900


# ── Репортер без настройки ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_without_config_logs_only() -> None:
    """Без BOT_TOKEN/админатов репортер не шлёт, но и не падает."""
    reporter = ErrorReporter(bot_token="", admin_ids=[], enabled=True)
    assert await reporter.report({"name": "X", "message": "y"}) is False
