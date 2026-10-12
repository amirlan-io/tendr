from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import supplier_agent as supplier_module
from app.agents.supplier_agent import (
    Requirement, SupplierAgent, SupplierCandidate, result_matches_requirement,
    search_query_pair, source_page_rank,
)


FILTER_URL = "https://kaspi.kz/shop/p/toplivnyi-fil-tr-13592436-108443317"
REGULATOR_URL = "https://pressure.kz/product/regulyator-davleniya-du80"


def test_exact_query_omits_order_quantity_and_kaspi_is_product_page():
    req = Requirement("f", "Топливный фильтр 13592436", "Для Chevrolet Cobalt. Количество 10 шт.")
    exact, broad = search_query_pair(req, "Астана")
    assert "13592436" in exact
    assert "10 шт" not in exact
    assert "Астана" in broad
    assert source_page_rank(FILTER_URL) == 0
    assert source_page_rank("https://www.olx.kz/zapchasti/q-toplivnyi-filtr") == 2
    regulator = Requirement("r", "Регулятор давления", "Стальной фланцевый 80 мм, 60,3 МПа")
    precise, relaxed = search_query_pair(regulator)
    assert "60,3" in precise
    assert "80 мм" in relaxed and "фланцев" in relaxed
    assert "60,3" not in relaxed
    desk = Requirement("d", "Стол офисный")
    assert "офисная мебель" in search_query_pair(
        desk, "Астана", ["офисная мебель"]
    )[1]


def test_search_result_requires_product_name_not_one_word():
    req = Requirement("r", "Регулятор давления")
    assert not result_matches_requirement({"title": "Регулятор температуры"}, req)
    assert result_matches_requirement({"title": "Регуляторы давления промышленные"}, req)


@pytest.mark.asyncio
async def test_each_position_gets_search_with_bounded_fallback(monkeypatch):
    monkeypatch.setattr(supplier_module, "get_settings", lambda: SimpleNamespace(
        supplier_search_max_calls=3, tavily_api_key="", browser_use_api_key=""))
    agent = SupplierAgent()
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        query = kwargs["query"]
        if "Топливный фильтр" in query:
            rows = [{"url": FILTER_URL, "title": "Топливный фильтр 13592436", "content": "Chevrolet Cobalt", "score": 0.9}]
        elif "60,3" in query:
            rows = [{"url": "https://fluid.kz/regulators", "title": "Регуляторы давления", "content": "Каталог", "score": 0.9}]
        else:
            rows = [{"url": REGULATOR_URL, "title": "Регулятор давления Ду80", "content": "Стальной фланцевый 80 мм", "score": 0.8}]
        return {"results": rows}

    agent._tavily_client = SimpleNamespace(search=search)
    reqs = [
        Requirement("f", "Топливный фильтр 13592436", "Количество 10 шт."),
        Requirement("r", "Регулятор давления", "Стальной, фланцевый, проход 80 мм, давление 60,3 МПа"),
    ]
    candidates, costs, meta = await agent.find_suppliers(
        reqs, enrich_browser=False, perform_matching=False
    )
    assert costs.tavily_calls == 3
    assert len(calls) == 3
    assert all(call["search_depth"] == "basic" for call in calls)
    assert any("60,3" in q for q in meta["queries"])
    assert {FILTER_URL, REGULATOR_URL} <= {c.url for c in candidates}
    assert meta["search_call_limit"] == 3


@pytest.mark.asyncio
async def test_search_does_not_spend_credits_without_client(monkeypatch):
    monkeypatch.setattr(supplier_module, "get_settings", lambda: SimpleNamespace(
        supplier_search_max_calls=6, tavily_api_key="", browser_use_api_key=""))
    agent = SupplierAgent()
    candidates, costs, meta = await agent.find_suppliers(
        [Requirement("r", "Регулятор давления")], enrich_browser=False, perform_matching=False
    )
    assert candidates == []
    assert costs.tavily_calls == 0
    assert meta["queries"] == []


@pytest.mark.asyncio
async def test_search_credit_cap_counts_failed_requests(monkeypatch):
    monkeypatch.setattr(supplier_module, "get_settings", lambda: SimpleNamespace(
        supplier_search_max_calls=2, tavily_api_key="", browser_use_api_key=""))
    agent = SupplierAgent()
    attempts = []
    def failing_search(**kwargs):
        attempts.append(kwargs["query"])
        raise RuntimeError("temporary search error")
    agent._tavily_client = SimpleNamespace(search=failing_search)
    candidates, costs, meta = await agent.find_suppliers(
        [Requirement("r", "Регулятор давления", "Стальной фланцевый 80 мм 60,3 МПа")],
        enrich_browser=False, perform_matching=False,
    )
    assert candidates == []
    assert len(attempts) == costs.tavily_calls == 2
    assert meta["direct_queries"] == []


@pytest.mark.asyncio
async def test_foreign_product_does_not_hide_kazakhstan_fallback(monkeypatch):
    monkeypatch.setattr(supplier_module, "get_settings", lambda: SimpleNamespace(
        supplier_search_max_calls=2, tavily_api_key="", browser_use_api_key=""))
    agent = SupplierAgent()
    attempts = []
    def search(**kwargs):
        attempts.append(kwargs["query"])
        url = ("https://foreign.ru/product/regulyator-davleniya" if len(attempts) == 1
               else REGULATOR_URL)
        return {"results": [{"url": url, "title": "Регулятор давления Ду80",
                             "content": "Стальной фланцевый", "score": 0.8}]}
    agent._tavily_client = SimpleNamespace(search=search)
    candidates, costs, meta = await agent.find_suppliers(
        [Requirement("r", "Регулятор давления", "Стальной фланцевый 80 мм")],
        enrich_browser=False, perform_matching=False,
    )
    assert len(attempts) == costs.tavily_calls == 2
    assert REGULATOR_URL in {c.url for c in candidates}
    assert meta["missing_product_codes"] == []


@pytest.mark.asyncio
async def test_first_search_pass_covers_all_items_before_fallback(monkeypatch):
    monkeypatch.setattr(supplier_module, "get_settings", lambda: SimpleNamespace(
        supplier_search_max_calls=2, tavily_api_key="", browser_use_api_key=""))
    agent = SupplierAgent()
    attempts = []
    def empty_search(**kwargs):
        attempts.append(kwargs["query"])
        return {"results": []}
    agent._tavily_client = SimpleNamespace(search=empty_search)
    reqs = [Requirement("f", "Топливный фильтр"), Requirement("r", "Регулятор давления")]
    _candidates, costs, meta = await agent.find_suppliers(
        reqs, enrich_browser=False, perform_matching=False,
    )
    assert len(attempts) == costs.tavily_calls == 2
    assert "Топливный фильтр" in attempts[0]
    assert "Регулятор давления" in attempts[1]
    assert meta["missing_product_codes"] == ["f", "r"]


def test_lot_budget_remains_incomplete_until_each_item_has_verified_offer():
    filter_req = Requirement("f", "Топливный фильтр", "Количество 10 шт.")
    regulator_req = Requirement("r", "Регулятор давления", "Количество 1 шт.")
    filter_card = SupplierCandidate("Kaspi", "kaspi.kz", "Топливный фильтр", url=FILTER_URL,
                                    price_kzt=2692, sources={"price": FILTER_URL},
                                    requirement_matches=[{"code": "f", "status": "fits"}])
    agent = SupplierAgent()
    partial = agent.summarize_lot_budget([filter_card], [filter_req, regulator_req], 48000)
    assert partial["status"] == "incomplete"
    assert partial["missing_codes"] == ["r"]
    assert partial["selected_goods_kzt"] is None
    regulator = SupplierCandidate("Store", "store.kz", "Регулятор давления", url=REGULATOR_URL,
                                  price_kzt=5000, sources={"price": REGULATOR_URL},
                                  requirement_matches=[{"code": "r", "status": "fits"}])
    complete = agent.summarize_lot_budget([filter_card, regulator], [filter_req, regulator_req], 48000)
    assert complete["selected_goods_kzt"] == 31920
    assert complete["status"] == "goods_within_budget_delivery_unknown"
    assert complete["delivery_included"] is False


@pytest.mark.asyncio
async def test_olx_search_page_cannot_be_full_product_match(monkeypatch):
    monkeypatch.setattr(supplier_module, "get_settings", lambda: SimpleNamespace(
        supplier_search_max_calls=0, tavily_api_key="", browser_use_api_key=""))
    agent = SupplierAgent()
    agent._chat_json = AsyncMock(return_value={"requirement_matches": [
        {"code": "f", "status": "fits", "source_url":
         "https://www.olx.kz/zapchasti/q-toplivnyi-filtr"}
    ]})
    candidate = SupplierCandidate("OLX", "olx.kz", "Топливный фильтр",
                                  url="https://www.olx.kz/zapchasti/q-toplivnyi-filtr",
                                  evidence_text="Топливный фильтр для автомобиля")
    await agent.match_requirements([candidate], [Requirement("f", "Топливный фильтр")])
    assert candidate.requirement_matches[0]["status"] == "partial"
