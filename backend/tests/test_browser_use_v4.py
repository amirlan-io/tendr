"""Тесты Browser Use Cloud v4 клиента.

Сеть не вызывается: httpx перехвачен заглушкой. Это принципиально —
проверка не должна создавать платные run'ы.

Покрыты гарантии, из-за которых модуль и писался:
* maxCostUsd приходит в каждый запрос и ограничен сверху;
* неоднозначный create не повторяется;
* браузер останавливается в любом исходе, включая таймаут;
* ключ не попадает в тело, URL и логи;
* мусорный результат не превращается в «данные».
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agents.browser_use.v4 import (
    DEFAULT_MAX_COST_USD,
    DEFAULT_MODEL,
    HARD_MAX_COST_USD,
    BrowserUseAmbiguousCreateError,
    BrowserUseError,
    BrowserUseNotConfigured,
    BrowserUseRunFailed,
    BrowserUseRunTimeout,
    BrowserUseV4Client,
    clamp_max_cost_usd,
    clamp_proxy_country,
    extract_json_object,
)

KEY = "bu_test_secret_key_do_not_log"


class FakeResponse:
    """Минимальный ответ httpx для подмены транспорта."""

    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    @property
    def content(self) -> bytes:
        return self.text.encode()

    def json(self) -> Any:
        return self._payload


def make_client(**kwargs: Any) -> BrowserUseV4Client:
    return BrowserUseV4Client(api_key=KEY, **kwargs)


def patch_transport(monkeypatch: pytest.MonkeyPatch, handler) -> list[dict[str, Any]]:
    """Подменяет httpx.AsyncClient и собирает все исходящие вызовы."""
    calls: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def request(self, method, url, headers=None, json=None, **kw):
            calls.append(
                {"method": method, "url": url, "headers": headers, "json": json}
            )
            response = handler(method, url, json)
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return calls


# ── Конфигурация ──────────────────────────────────────────────────────


def test_missing_api_key_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.browser_use.v4.get_settings",
        lambda: type("S", (), {"browser_use_api_key": ""})(),
    )
    with pytest.raises(BrowserUseNotConfigured) as exc:
        BrowserUseV4Client()
    assert "BROWSER_USE_API_KEY" in str(exc.value)


def test_defaults_are_documented_values() -> None:
    client = make_client()
    assert client.model == DEFAULT_MODEL == "gpt-5.6-luna"
    assert client.max_cost_usd == DEFAULT_MAX_COST_USD == 1.0


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, DEFAULT_MAX_COST_USD),
        (0, DEFAULT_MAX_COST_USD),
        (-5, DEFAULT_MAX_COST_USD),
        ("мусор", DEFAULT_MAX_COST_USD),
        (0.5, 0.5),
        (999, HARD_MAX_COST_USD),  # опечатка не станет неограниченным счётом
    ],
)
def test_max_cost_is_clamped(value: Any, expected: float) -> None:
    assert clamp_max_cost_usd(value) == pytest.approx(expected)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("KZ", "kz"),
        (" kz ", "kz"),
        ("", None),
        ("kaz", None),  # не ISO-3166-1 alpha-2
        (None, None),
    ],
)
def test_proxy_country_normalization(value: Any, expected: Any) -> None:
    assert clamp_proxy_country(value) == expected


# ── Создание запроса ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_run_sends_model_and_cost_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_transport(
        monkeypatch, lambda m, u, b: FakeResponse({"id": "run-1", "sessionId": "s-1"})
    )
    client = make_client()
    out = await client.create_run("Найди цену", proxy_country_code="kz")

    assert out["id"] == "run-1"
    body = calls[0]["json"]
    assert body["model"] == "gpt-5.6-luna"
    assert body["maxCostUsd"] == pytest.approx(1.0)
    # Прокси едет только вместе с browserSettings
    assert body["browserSettings"]["proxyCountryCode"] == "kz"
    assert body["task"] == "Найди цену"


@pytest.mark.asyncio
async def test_create_run_without_proxy_has_no_browser_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_transport(monkeypatch, lambda m, u, b: FakeResponse({"id": "r"}))
    client = make_client()

    await client.create_run("задача")
    assert "browserSettings" not in calls[0]["json"]


@pytest.mark.asyncio
async def test_create_run_respects_explicit_lower_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_transport(monkeypatch, lambda m, u, b: FakeResponse({"id": "r"}))
    client = make_client()

    await client.create_run("задача", max_cost_usd=0.25)
    assert calls[0]["json"]["maxCostUsd"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_create_run_rejects_empty_task() -> None:
    client = make_client()
    with pytest.raises(BrowserUseError):
        await client.create_run("   ")


@pytest.mark.asyncio
async def test_api_key_never_leaves_the_header(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_transport(monkeypatch, lambda m, u, b: FakeResponse({"id": "r"}))
    client = make_client()
    await client.create_run("задача")

    call = calls[0]
    # Ключ только в заголовке — ни в теле, ни в URL
    assert call["headers"]["X-Browser-Use-API-Key"] == KEY
    assert KEY not in json.dumps(call["json"])
    assert KEY not in call["url"]
    # Без префикса Bearer — так требует V4
    assert not call["headers"]["X-Browser-Use-API-Key"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_key_is_redacted_in_error_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_transport(
        monkeypatch,
        lambda m, u, b: FakeResponse({}, status_code=500, text=f"failed for key {KEY}"),
    )
    client = make_client()
    with pytest.raises(BrowserUseError) as exc:
        await client.create_run("задача")
    assert KEY not in str(exc.value)
    assert "***" in str(exc.value)


# ── Неоднозначный create не повторяется ───────────────────────────────


@pytest.mark.asyncio
async def test_network_error_raises_ambiguous_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_transport(
        monkeypatch, lambda m, u, b: httpx.ConnectTimeout("timed out")
    )
    client = make_client()
    with pytest.raises(BrowserUseAmbiguousCreateError):
        await client.create_run("задача")
    # Ровно одна попытка: повтор создал бы второй платный run
    assert len(calls) == 1


# ── Ожидание и очистка ресурсов ───────────────────────────────────────


def _completed_handler(status: str = "completed", result: str = "", error: str = ""):
    def handler(method, url, body):
        if method == "POST" and url.endswith("/runs"):
            return FakeResponse({"id": "run-9", "sessionId": "sess-9"})
        if url.endswith("/status"):
            return FakeResponse({"status": status})
        if url.endswith("/cancel"):
            return FakeResponse({"ok": True})
        if method == "GET" and url.endswith("/runs/run-9"):
            return FakeResponse(
                {
                    "id": "run-9",
                    "status": status,
                    "result": result,
                    "error": error,
                    "totalCostUsd": 0.31,
                    "model": "gpt-5.6-luna",
                    "sessionId": "sess-9",
                }
            )
        if method == "PATCH" and "/browsers/" in url:
            return FakeResponse({"id": "sess-9", "status": "stopped"})
        return FakeResponse({}, status_code=404)

    return handler


@pytest.mark.asyncio
async def test_run_task_returns_result_and_stops_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_transport(
        monkeypatch,
        _completed_handler(result='{"price_kzt": 45990, "email": "sales@shop.kz"}'),
    )
    client = make_client()
    result = await client.run_task("задача")

    assert result.ok
    assert result.run_id == "run-9"
    assert result.total_cost_usd == pytest.approx(0.31)
    assert extract_json_object(result.result)["price_kzt"] == 45990

    # Браузер остановлен — иначе биллинг продолжает идти
    stops = [c for c in calls if c["method"] == "PATCH"]
    assert len(stops) == 1
    assert stops[0]["json"] == {"action": "stop"}
    assert stops[0]["url"].endswith("/browsers/sess-9")


@pytest.mark.asyncio
async def test_timeout_cancels_run_and_stops_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(method, url, body):
        if method == "POST" and url.endswith("/runs"):
            return FakeResponse({"id": "run-t", "sessionId": "sess-t"})
        if url.endswith("/status"):
            return FakeResponse({"status": "running"})  # вечно работает
        if url.endswith("/cancel"):
            return FakeResponse({"ok": True})
        if method == "PATCH":
            return FakeResponse({"status": "stopped"})
        return FakeResponse({}, status_code=404)

    calls = patch_transport(monkeypatch, handler)
    client = make_client()

    with pytest.raises(BrowserUseRunTimeout):
        await client.run_task("задача", timeout=1.0, poll_interval=0.5)

    # Брошенный run отменён И браузер остановлен
    assert any(c["url"].endswith("/cancel") for c in calls)
    assert any(c["method"] == "PATCH" for c in calls)


@pytest.mark.asyncio
async def test_failed_status_raises_and_still_stops_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_transport(
        monkeypatch,
        _completed_handler(status="failed", error="navigation blocked"),
    )
    client = make_client()

    with pytest.raises(BrowserUseRunFailed) as exc:
        await client.run_task("задача")
    assert exc.value.status == "failed"
    assert any(c["method"] == "PATCH" for c in calls)


@pytest.mark.asyncio
async def test_stop_browser_tolerates_missing_session() -> None:
    client = make_client()
    assert await client.stop_browser(None) is False


# ── Валидация результата ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        '{"price_kzt": 45990}',
        '```json\n{"price_kzt": 45990}\n```',
        'Вот результат: {"price_kzt": 45990} — всё готово',
    ],
)
def test_extract_json_handles_common_shapes(raw: str) -> None:
    parsed = extract_json_object(raw)
    assert parsed is not None
    assert parsed["price_kzt"] == 45990


@pytest.mark.parametrize("raw", ["", "нет json", "[1,2,3]", "{битый json"])
def test_extract_json_rejects_garbage(raw: str) -> None:
    assert extract_json_object(raw) is None


@pytest.mark.asyncio
async def test_run_task_returns_raw_string_not_fake_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Мусорный result остаётся строкой — мы не выдумываем данные."""
    patch_transport(
        monkeypatch, _completed_handler(result="не смог найти цену")
    )
    client = make_client()
    result = await client.run_task("задача")
    assert result.result == "не смог найти цену"
    assert extract_json_object(result.result) is None