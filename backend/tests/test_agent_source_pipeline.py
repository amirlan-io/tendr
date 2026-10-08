from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.documenter import DocumenterAgent
from app.agents.supplier_agent import (
    Costs, Requirement, SupplierAgent, SupplierCandidate, evidence_coverage, source_page_rank,
)
from app.agents.product_search import ProductSearchAgent
from app.schemas.lot import ProductSearchRequest


@pytest.mark.asyncio
async def test_documenter_retains_all_positions_and_excludes_invented_documents(monkeypatch):
    agent = DocumenterAgent()
    items = [{"name": f"Товар {i}", "value": "Материал сталь", "quantity": i,
              "unit": "шт.", "category": "goods"} for i in range(1, 8)]
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(return_value={
        "title": "Закупка", "requirements": items, "payment_terms": "30 дней",
        "documents_required": ["Сертификат", "Выдуманная справка"],
    }))
    result = await agent.run("Поставка товаров. Требуется Сертификат.", lot_id="test")
    assert len(result.requirements) == 7
    assert len({r.code for r in result.requirements}) == 7
    assert result.requirements[6].quantity == 7
    assert "Количество 7 шт." in result.requirements[6].value
    assert result.documents_required == ["Сертификат"]
    assert result.payment_terms == "30 дней"


@pytest.mark.asyncio
async def test_middle_of_long_document_is_processed(monkeypatch):
    agent = DocumenterAgent()
    prompts = []
    async def reply(prompt, **kwargs):
        prompts.append(prompt)
        return {"title": "Закупка", "requirements": [{"name": "Сканер", "value": "50 листов"}]} if "СКАНЕР_В_СЕРЕДИНЕ" in prompt else {"title": "Закупка"}
    monkeypatch.setattr(agent, "_chat_json", reply)
    text = "А" * 11000 + "СКАНЕР_В_СЕРЕДИНЕ" + "Б" * 11000
    result = await agent.run(text, lot_id="test")
    assert len(prompts) == 3
    assert result.requirements[0].name == "Сканер"
    assert result.technical_specification == text


def test_order_quantity_does_not_require_quantity_in_product_specification():
    req = Requirement("f", "Топливный фильтр", "Автомобильный, количество 10 шт.")
    found, total = evidence_coverage(req, "Автомобильный топливный фильтр")
    assert found == total


def test_concrete_product_pages_rank_ahead_of_search_results():
    assert source_page_rank("https://store.kz/p12345-stol.html") < source_page_rank("https://flagma.kz/products/astana?q=стол")


def test_dimensions_with_shared_unit_are_equivalent():
    req = Requirement("desk", "Стол", "Размер 1500х700 мм, высота 750 мм, ЛДСП 16 мм. 2 шт.")
    found, total = evidence_coverage(req, "Стол: 1500*700*750мм, ЛДСП 16 мм")
    assert found == total


@pytest.mark.asyncio
async def test_delivery_included_in_goods_price_is_not_another_product(monkeypatch):
    agent = DocumenterAgent()
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(return_value={
        "title": "Стол", "requirements": [
            {"name": "Стол", "value": "2 шт.", "category": "goods"},
            {"name": "Доставка и сборка", "value": "Включены в цену товара", "category": "service"},
        ]}))
    result = await agent.run("Стол, доставка и сборка включены в цену товара", lot_id="test")
    assert [r.name for r in result.requirements] == ["Стол"]
    assert "Включены" in result.delivery_terms


@pytest.mark.asyncio
async def test_invented_source_quote_is_not_exposed_as_verified(monkeypatch):
    agent = DocumenterAgent()
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(return_value={
        "title": "Стол", "requirements": [{"name": "Стол", "value": "ЛДСП", "source_quote": "Стол из титана"}]}))
    result = await agent.run("Поставка стола из ЛДСП", lot_id="test")
    assert result.requirements[0].source_quote == ""
    assert result.warnings


@pytest.mark.asyncio
async def test_html_price_and_specification_are_read_without_rendering_fallback(monkeypatch):
    from app.agents import page_fetcher
    agent = SupplierAgent()
    monkeypatch.setattr(page_fetcher, "is_public_http_url", lambda url: True)
    html = '''<html><nav>Other products</nav><body>
    <h1>Стол офисный</h1><table><tr><td>Стол офисный</td><td>1</td></tr></table>
    <div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Стол офисный</span>
    <meta itemprop="price" content="41700"><meta itemprop="priceCurrency" content="KZT"></div>
    <p>Размеры 1500*700*750 мм. Толщина столешницы 16 мм. Опоры ламинированная ДСП.</p>
    <p>Телефон +7 701 760 67 11. В наличии.</p></body></html>'''
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    fallback = AsyncMock()
    monkeypatch.setattr(page_fetcher, "fetch_page", fallback)
    candidate = SupplierCandidate("Арлан", "store.kz", "Стол офисный", url="https://store.kz/p123.html")
    costs = await agent.enrich_with_pages([candidate], terms=["Стол офисный"])
    assert candidate.price_kzt == 41700
    assert "16 мм" in candidate.evidence_text
    assert candidate.phone
    assert costs.page_fetch_count == 1
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_product_search_uses_verified_candidates_and_discards_mismatches(monkeypatch):
    good = SupplierCandidate("Store", "store.kz", "Стол", url="https://store.kz/p1.html", price_kzt=41700, score=50,
        requirement_matches=[{"code": "product", "status": "partial", "comment": "Гарантия неизвестна"}])
    bad = SupplierCandidate("Wrong", "wrong.kz", "Стеллаж", score=0,
        requirement_matches=[{"code": "product", "status": "no"}])
    finder = AsyncMock(return_value=([good, bad], Costs(), {"queries": ["Стол Казахстан"]}))
    monkeypatch.setattr(SupplierAgent, "find_suppliers", finder)
    agent = ProductSearchAgent()
    result = await agent.run(ProductSearchRequest(query="Стол", quantity=2))
    assert [p.name for p in result.products] == ["Стол"]
    assert result.products[0].price_kzt == 41700
    assert finder.call_args.kwargs["allow_browser_fallback"] is False


@pytest.mark.asyncio
async def test_generic_provider_uses_configured_service_instead_of_alem(monkeypatch):
    from app.llm import mistral as factory
    settings = SimpleNamespace(llm_provider="openai-compatible", llm_api_key="test",
        llm_base_url="https://anymodel.org/v1/chat/completions", llm_model="catalog-model",
        llm_embedding_model="embed", llm_api_key_fallback="", alem_base_url="https://wrong.example", alem_model="wrong")
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_provider", None)
    provider = factory.get_llm()
    try:
        assert provider._base_url == "https://anymodel.org/v1"
        assert provider._model == "catalog-model"
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_batch_matching_keeps_supplier_evidence_separate(monkeypatch):
    agent = SupplierAgent()
    chat = AsyncMock(return_value={"candidates": [
        {"candidate_id": "candidate_0", "requirement_matches": [{"code": "desk", "status": "no"}]},
        {"candidate_id": "candidate_1", "requirement_matches": [{"code": "desk", "status": "fits", "source_url": "https://good.kz/p1.html"}]},
    ]})
    monkeypatch.setattr(agent, "_chat_json", chat)
    bad = SupplierCandidate("Wrong", "wrong.kz", "Стеллаж", url="https://wrong.kz/p1.html", evidence_text="Стеллаж")
    good = SupplierCandidate("Good", "good.kz", "Стол", url="https://good.kz/p1.html", evidence_text="Стол офисный")
    costs = await agent.match_requirements([bad, good], [Requirement("desk", "Стол офисный")])
    assert bad.requirement_matches[0]["status"] == "no"
    assert good.requirement_matches[0]["status"] == "fits"
    assert costs.llm_calls == 1
    chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_borrowed_source_cannot_confirm_another_candidate(monkeypatch):
    agent = SupplierAgent()
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(return_value={
        "requirement_matches": [{"code": "desk", "status": "fits", "source_url": "https://other.kz"}]}))
    candidate = SupplierCandidate("Test", "test.kz", "Стол", url="https://test.kz/p1.html", evidence_text="Стол офисный")
    await agent.match_requirements([candidate], [Requirement("desk", "Стол офисный")])
    assert candidate.requirement_matches[0]["status"] == "unknown"
    assert candidate.score == 0


@pytest.mark.asyncio
async def test_structured_price_and_stock_belong_to_same_product(monkeypatch):
    from app.agents import page_fetcher
    monkeypatch.setattr(page_fetcher, "is_public_http_url", lambda url: True)
    html = '''<html><body><p>Каталог мебели. Другие товары в наличии.</p>
    <script type="application/ld+json">[
    {"@type":"Product","name":"Стул","offers":{"price":1000,"priceCurrency":"KZT","availability":"https://schema.org/InStock"}},
    {"@type":"Product","name":"Стол офисный","offers":{"price":41700,"priceCurrency":"KZT","availability":"https://schema.org/OutOfStock"}}
    ]</script><p>Стол офисный из ЛДСП. Подробные характеристики, оплата и доставка мебели по Казахстану.</p></body></html>'''
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    candidate = SupplierCandidate("Store", "store.kz", "Стол офисный", url="https://store.kz/p1.html", price_kzt=1)
    await SupplierAgent()._apply_structured_prices(candidate, terms=["Стол офисный"])
    assert candidate.price_kzt == 41700
    assert candidate.in_stock is False


@pytest.mark.asyncio
async def test_all_requirement_codes_are_sent_to_matching(monkeypatch):
    agent = SupplierAgent()
    chat = AsyncMock(return_value={})
    monkeypatch.setattr(agent, "_chat_json", chat)
    requirements = [Requirement(f"item_{i}", f"Товар {i}") for i in range(25)]
    await agent.match_requirements([SupplierCandidate("Store", "store.kz", "Каталог")], requirements)
    assert "[item_24]" in chat.call_args.args[0]
    assert len(requirements) * 350 <= chat.call_args.kwargs["max_tokens"]


@pytest.mark.asyncio
async def test_documents_from_later_chunks_are_merged_and_failures_visible(monkeypatch):
    agent = DocumenterAgent()
    monkeypatch.setattr(agent, "_chat_json", AsyncMock(side_effect=[
        {"title": "Закупка", "documents_required": ["Сертификат"]},
        {"documents_required": ["Паспорт"]}, {},
    ]))
    result = await agent.run("Сертификат " + "А" * 10000 + "Паспорт " + "Б" * 10000, lot_id="test")
    assert result.documents_required == ["Сертификат", "Паспорт"]
    assert any("фрагментов" in warning for warning in result.warnings)


def test_product_identifiers_are_not_supplier_phone_numbers():
    from app.agents.supplier_agent import find_contacts
    assert find_contacts("Артикул 87947351247, штрихкод 9879473512478")[1] == ""
    assert find_contacts("Телефон: 87017606711")[1] == "87017606711"
    assert find_contacts("Контакты: +7 (701) 760-67-11")[1] == "+7 (701) 760-67-11"


def test_contacts_section_does_not_prove_direct_supplier():
    from app.agents.supplier_agent import looks_like_manufacturer
    assert not looks_like_manufacturer("О нас. Контакты. Контактная информация магазина.")
    assert looks_like_manufacturer("Собственное производство офисной мебели")


@pytest.mark.asyncio
async def test_order_quantity_is_not_in_model_characteristic_check(monkeypatch):
    agent = SupplierAgent()
    chat = AsyncMock(return_value={})
    monkeypatch.setattr(agent, "_chat_json", chat)
    await agent.match_requirements([SupplierCandidate("Store", "store.kz", "Фильтр")],
                                   [Requirement("filter", "Фильтр", "Для легкового автомобиля. Количество 10 шт.")])
    assert "10 шт" not in chat.call_args.args[0]
    assert "легкового автомобиля" in chat.call_args.args[0]


@pytest.mark.asyncio
async def test_browser_fallback_stops_after_account_credit_failure():
    from app.agents.browser_use import BrowserUseError
    agent = SupplierAgent()
    browser = SimpleNamespace(run_task=AsyncMock(side_effect=BrowserUseError("402: no credits")))
    agent._browser_agent = browser
    candidates = [SupplierCandidate("A", "a.kz", "Стол", url="https://a.kz/p1"),
                  SupplierCandidate("B", "b.kz", "Стол", url="https://b.kz/p2")]
    costs = await agent.enrich_with_browser(candidates, top_n=2)
    assert browser.run_task.await_count == 1
    assert browser.run_task.call_args.kwargs["model"] == "bu-mini"
    assert costs.browser_calls == 0
    assert candidates[0].warnings == ["Не удалось проверить страницу поставщика."]
