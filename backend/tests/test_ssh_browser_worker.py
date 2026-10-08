from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import ssh_browser
from app.agents.supplier_agent import Requirement, SupplierAgent, SupplierCandidate


URL = "https://kaspi.kz/shop/p/toplivnyi-fil-tr-13592436-108443317"


def test_kaspi_canonical_trailing_slash_is_same_product():
    from scripts.ssh_browser_worker import same_product_page
    assert same_product_page(URL, URL + "/")
    assert not same_product_page(URL, "https://kaspi.kz/shop/p/another-product/")


@pytest.mark.parametrize("url", [
    "http://kaspi.kz/shop/p/item", "https://kaspi.kz.evil.org/shop/p/item",
    "https://user@kaspi.kz/shop/p/item", "https://kaspi.kz:8443/shop/p/item",
    "https://kaspi.kz:invalid/shop/p/item",
    "https://kaspi.kz/shop/search?q=x", "file:///etc/passwd",
])
def test_browser_worker_rejects_other_urls(url):
    assert not ssh_browser.is_supported_product_url(url)


@pytest.mark.asyncio
async def test_supplier_uses_verified_browser_price_and_specification(monkeypatch):
    from app.agents import page_fetcher
    agent = SupplierAgent()
    rendered = {
        "url": URL, "product_title": "Топливный фильтр 13592436",
        "city": "Астана", "price_kzt": 2692,
        "evidence_text": "Код товара: 108443317. Chevrolet Cobalt. Тип: топливный фильтр. OEM 13592336",
    }
    browser = AsyncMock(return_value=rendered)
    fallback = AsyncMock()
    monkeypatch.setattr(ssh_browser, "read_product", browser)
    monkeypatch.setattr(page_fetcher, "fetch_page", fallback)
    candidate = SupplierCandidate("Kaspi", "kaspi.kz", "Топливный фильтр", url=URL)
    costs = await agent.enrich_with_pages([candidate], region_hint="Астана")
    assert candidate.price_kzt == 2692
    assert candidate.city == "Астана"
    assert "Cobalt" in candidate.evidence_text
    assert candidate.sources["price_source"] == "ssh_browser"
    from app.api.sandbox import _card
    assert _card(candidate)["sources"]["price_source"] == "ssh_browser"
    assert costs.page_fetch_count == 1
    browser.assert_awaited_once_with(URL, city="Астана")
    fallback.assert_not_awaited()
    req = Requirement("filter", "Топливный фильтр", "Chevrolet Cobalt, 10 шт.")
    agent.assess_budget([candidate], [req], 48000)
    assert candidate.estimated_total_kzt == 26920
    assert candidate.budget_status == "within_budget"


@pytest.mark.asyncio
async def test_browser_read_failure_falls_back_to_existing_reader(monkeypatch):
    from app.agents import page_fetcher
    agent = SupplierAgent()
    monkeypatch.setattr(ssh_browser, "read_product", AsyncMock(return_value=None))
    monkeypatch.setattr(agent, "_apply_structured_prices", AsyncMock())
    monkeypatch.setattr(page_fetcher, "fetch_page", AsyncMock(return_value=SimpleNamespace(
        is_usable=True, text="Топливный фильтр 13592436 для Chevrolet Cobalt", provider="jina")))
    candidate = SupplierCandidate("Kaspi", "kaspi.kz", "Топливный фильтр", url=URL)
    costs = await agent.enrich_with_pages([candidate])
    assert costs.page_fetch_count == 1
    assert "Chevrolet" in candidate.evidence_text


@pytest.mark.asyncio
async def test_product_cards_after_page_window_are_still_checked(monkeypatch):
    from app.agents import page_fetcher
    agent = SupplierAgent()
    monkeypatch.setattr(agent, "_apply_structured_prices", AsyncMock())
    monkeypatch.setattr(page_fetcher, "fetch_page", AsyncMock(return_value=SimpleNamespace(
        is_usable=True, text="Каталог оборудования", provider="jina")))
    browser = AsyncMock(return_value={
        "url": URL, "product_title": "Топливный фильтр 13592436",
        "city": "Астана", "price_kzt": 2692, "evidence_text": "Chevrolet Cobalt",
    })
    monkeypatch.setattr(ssh_browser, "read_product", browser)
    category = SupplierCandidate("Каталог", "other.kz", "Оборудование", url="https://other.kz/catalog")
    product = SupplierCandidate("Kaspi", "kaspi.kz", "Фильтр", url=URL)
    costs = await agent.enrich_with_pages([category, product], top_n=1, region_hint="Астана")
    assert costs.page_fetch_count == 2
    assert product.price_kzt == 2692
    browser.assert_awaited_once_with(URL, city="Астана")
