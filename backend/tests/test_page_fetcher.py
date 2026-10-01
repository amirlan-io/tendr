"""Тесты бесплатного чтения страниц (Jina Reader + Tavily Extract).

Главное, что тут проверяется, — защита от SSRF: адреса приходят из
внешнего поиска, и без проверки агент заставил бы сервер ходить во
внутреннюю сеть (localhost, БД, Redis).

Сеть не вызывается: httpx перехвачен заглушкой.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agents.page_fetcher import (
    MAX_CONTENT_CHARS,
    PageContent,
    clean_jina_output,
    fetch_jina,
    fetch_page,
    is_public_http_url,
)

JINA_SAMPLE = (
    "Title: Фильтры автомобильные в Павлодаре\n"
    "URL Source: https://flagma.kz/products/filtry\n"
    "Markdown Content:\n"
    "## Фильтр гидравлический SH56760\n"
    "Цена: 5 000 тг\n"
    "В наличии. Павлодар. Тел: 7801-31090-30\n"
    "Пишите: sales@example.kz\n"
)


# ── SSRF-защита ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://flagma.kz/products/filtry",  # обычный публичный сайт
        "http://example.com/page",
    ],
)
def test_public_urls_are_allowed(url: str) -> None:
    assert is_public_http_url(url) is True


@pytest.mark.parametrize(
    "url,reason",
    [
        ("http://localhost:8000/api/health", "локальный API"),
        ("http://127.0.0.1/admin", "loopback"),
        ("http://10.0.0.5/secrets", "приватная сеть 10/8"),
        ("http://192.168.1.1/router", "приватная сеть 192.168/16"),
        ("http://172.17.0.2/db", "docker-сеть"),
        ("http://169.254.169.254/latest/meta-data", "метаданные облака"),
        ("http://[::1]/", "IPv6 loopback"),
        ("http://metadata.google.internal/x", "служебный домен"),
    ],
)
def test_internal_urls_are_blocked(url: str, reason: str) -> None:
    assert is_public_http_url(url) is False, reason


@pytest.mark.parametrize(
    "url,reason",
    [
        ("javascript:alert(1)", "не http"),
        ("file:///etc/passwd", "файловая схема"),
        ("data:text/html,<h1>x</h1>", "data-схема"),
        ("ftp://example.com", "не http"),
        ("https://user:pass@flagma.kz/", "userinfo в URL"),
        ("http://example.com:6379/", "нестандартный порт"),
        ("", "пустая строка"),
        ("не url вовсе", "мусор"),
    ],
)
def test_dangerous_urls_are_blocked(url: str, reason: str) -> None:
    assert is_public_http_url(url) is False, reason


def test_unresolvable_host_is_blocked() -> None:
    # Хост не резолвится — лучше не тратить время и не ходить по такому адресу.
    assert is_public_http_url("https://нет-такого-хоста-12345.kz") is False


@pytest.mark.asyncio
async def test_fetch_page_refuses_unsafe_url_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Небезопасный адрес не должен вызывать HTTP вообще."""

    def explode(*a: Any, **kw: Any):
        raise AssertionError("сеть не должна вызываться для небезопасного URL")

    monkeypatch.setattr(httpx, "AsyncClient", explode)
    page = await fetch_page("http://127.0.0.1:5432/")
    assert page.ok is False
    assert page.error == "blocked_unsafe_url"
    assert page.provider == "guard"


# ── Разбор ответа Jina ────────────────────────────────────────────────


def test_clean_jina_output_strips_service_header() -> None:
    cleaned = clean_jina_output(JINA_SAMPLE)
    # Служебные заголовки убраны, контент остался
    assert "Markdown Content:" not in cleaned
    assert "URL Source:" not in cleaned
    assert "Фильтр гидравлический" in cleaned


def test_clean_jina_output_truncates() -> None:
    long_text = "A" * (MAX_CONTENT_CHARS * 2)
    assert len(clean_jina_output(long_text)) == MAX_CONTENT_CHARS


@pytest.mark.asyncio
async def test_fetch_jina_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def get(self, url, headers=None):
            assert url.startswith("https://r.jina.ai/")
            return httpx.Response(200, text=JINA_SAMPLE)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    page = await fetch_jina("https://flagma.kz/products/filtry")
    assert page.is_usable
    assert page.provider == "jina"
    assert "5 000 тг" in page.text


@pytest.mark.asyncio
async def test_fetch_jina_handles_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def get(self, url, headers=None):
            return httpx.Response(429, text="rate limited")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    page = await fetch_jina("https://flagma.kz/products/filtry")
    assert page.ok is False
    assert "429" in page.error
    assert page.is_usable is False


# ── Разбор страницы в карточку поставщика ─────────────────────────────


@pytest.mark.asyncio
async def test_enrich_applies_contacts_price_and_city(monkeypatch: pytest.MonkeyPatch) -> None:
    """Страница -> контакты, цена, наличие, город."""
    from app.agents.supplier_agent import SupplierCandidate, SupplierAgent

    class FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def get(self, url, headers=None):
            return httpx.Response(200, text=JINA_SAMPLE)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    agent = SupplierAgent()
    candidate = SupplierCandidate(
        supplier="ООО Тест", domain="flagma.kz", title="Фильтр", url="https://flagma.kz/p"
    )
    costs = await agent.enrich_with_pages([candidate], top_n=1)

    assert candidate.email == "sales@example.kz"
    assert candidate.phone
    assert candidate.price_kzt == pytest.approx(5000.0)
    assert candidate.in_stock is True
    assert candidate.city == "Павлодар"
    assert costs.page_fetch_count == 1
    assert costs.browser_usd == 0.0  # платный браузер не понадобился


@pytest.mark.asyncio
async def test_unreadable_page_is_flagged_not_invented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если страница не прочитана — предупреждение, а не выдуманные данные."""
    from app.agents.supplier_agent import SupplierCandidate, SupplierAgent

    class FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def get(self, url, headers=None):
            return httpx.Response(404, text="not found")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    agent = SupplierAgent()
    candidate = SupplierCandidate(
        supplier="ООО Тест", domain="olx.kz", title="Вал", url="https://olx.kz/x"
    )
    await agent.enrich_with_pages([candidate], top_n=1)

    assert candidate.email == ""
    assert candidate.phone == ""
    assert candidate.price_kzt is None
    assert any("не удалось прочитать" in w for w in candidate.warnings)


@pytest.mark.asyncio
async def test_price_is_not_taken_from_unrelated_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Год выпуска или количество не должны становиться «ценой»."""
    from app.agents.supplier_agent import SupplierCandidate, SupplierAgent

    class FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def get(self, url, headers=None):
            text = "Markdown Content:\nГод выпуска: 2019. Вес: 3 500 г. Производство: 2024\n"
            return httpx.Response(200, text=text)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    agent = SupplierAgent()
    candidate = SupplierCandidate(
        supplier="ООО Тест", domain="x.kz", title="Т", url="https://x.kz/p"
    )
    await agent.enrich_with_pages([candidate], top_n=1)
    # Без маркера валюты цена не определяется
    assert candidate.price_kzt is None


def test_page_content_usability_flag() -> None:
    assert PageContent(url="u", text="что-то", provider="jina").is_usable is True
    assert PageContent(url="u", text="", provider="jina", ok=False).is_usable is False
    assert PageContent(url="u", text="   ", provider="jina").is_usable is False


def test_extract_contacts_reuses_supplier_parser() -> None:
    from app.agents.page_fetcher import extract_contacts

    email, phone = extract_contacts("Пишите sales@example.kz или звоните 7801-31090-30")
    assert email == "sales@example.kz"
    assert phone
