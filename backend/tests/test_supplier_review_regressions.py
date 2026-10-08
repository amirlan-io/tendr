"""Regressions from the live supplier review; no external services required."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.documenter import DocumenterAgent
from app.agents.structured_data import extract_products, pick_price
from app.agents.supplier_agent import (
    Costs, Requirement, SupplierAgent, SupplierCandidate, classify_domain,
    dedupe_requirements, has_mandatory_mismatch, score_from_matches,
)


@pytest.mark.parametrize("value", ["1", "25 мм", "1400", "2 шт."])
def test_product_attributes_are_not_prices(value):
    html = f'<table><tr><td>Стол офисный</td><td>{value}</td></tr></table>'
    assert pick_price(extract_products(html), "Стол офисный") is None


def test_quantity_table_does_not_shadow_real_offer():
    html = '''<table><tr><td>Стол офисный</td><td>1</td></tr></table>
    <div itemscope itemtype="https://schema.org/Product">
    <span itemprop="name">Стол офисный</span>
    <meta itemprop="price" content="41700">
    <meta itemprop="priceCurrency" content="KZT"></div>'''
    assert pick_price(extract_products(html), "Стол офисный") == 41700


def test_explicit_currency_table_still_extracts_price():
    html = '<table><tr><td>Стол офисный</td><td>41 700 ₸</td></tr></table>'
    assert pick_price(extract_products(html), "Стол офисный") == 41700


@pytest.mark.asyncio
async def test_unknown_model_codes_cannot_inflate_score(monkeypatch):
    agent = SupplierAgent()
    async def reply(*args, **kwargs):
        return {"requirement_matches": [
            {"code": "1.1", "title": "Размеры", "status": "fits"},
            {"code": "1.2", "title": "Материал", "status": "fits"},
        ]}
    monkeypatch.setattr(agent, "_chat_json", reply)
    candidate = SupplierCandidate("Test", "test.kz", "Стол")
    await agent.match_requirements([candidate], [Requirement("desk", "Стол офисный", is_mandatory=True)])
    assert [(m["code"], m["status"]) for m in candidate.requirement_matches] == [("desk", "unknown")]
    assert candidate.score == 0


@pytest.mark.asyncio
async def test_duplicate_matches_keep_worst_status(monkeypatch):
    agent = SupplierAgent()
    async def reply(*args, **kwargs):
        return {"requirement_matches": [
            {"code": "desk", "status": "fits"},
            {"code": "desk", "status": "no"},
            {"code": "desk", "status": "fits"},
        ]}
    monkeypatch.setattr(agent, "_chat_json", reply)
    candidate = SupplierCandidate("Test", "test.kz", "Стол")
    reqs = [Requirement("desk", "Стол офисный", is_mandatory=True)]
    await agent.match_requirements([candidate], reqs)
    assert len(candidate.requirement_matches) == 1
    assert candidate.score == 0
    assert has_mandatory_mismatch(candidate, reqs)


def test_unknown_data_is_not_confirmed_compliance():
    assert score_from_matches([{"status": "unknown"}] * 5) == 0


def test_missing_or_duplicate_requirement_codes_are_stable_and_unique():
    raw = [Requirement("", "Стол"), Requirement("desk", "Стул"), Requirement("desk", "Шкаф")]
    normalized = dedupe_requirements(raw)
    assert len({r.code for r in normalized}) == 3
    assert all(r.code for r in normalized)
    assert [r.code for r in dedupe_requirements(raw)] == [r.code for r in normalized]
    assert raw[0].code == ""


@pytest.mark.parametrize("domain", ["wikipedia.org", "news.example.org", "unknown.example.org"])
def test_unknown_domain_does_not_prove_direct_supplier(domain):
    assert classify_domain(domain) == "unknown"


def test_partial_lot_price_does_not_confirm_whole_budget():
    candidate = SupplierCandidate("Test", "test.kz", "Топливный фильтр", price_kzt=4000)
    reqs = [Requirement("filter", "Топливный фильтр", "10 шт."),
            Requirement("regulator", "Регулятор давления", "1 шт.")]
    SupplierAgent.assess_budget([candidate], reqs, 48000)
    assert candidate.estimated_total_kzt == 40000
    assert candidate.budget_status == "unknown"


def test_single_position_budget_with_explicit_quantity():
    candidate = SupplierCandidate("Test", "test.kz", "Стол офисный", price_kzt=41700)
    SupplierAgent.assess_budget([candidate], [Requirement("desk", "Стол офисный", "2 шт.")], 100000)
    assert candidate.estimated_total_kzt == 83400
    assert candidate.budget_status == "within_budget"


def test_missing_quantity_does_not_assume_one():
    candidate = SupplierCandidate("Test", "test.kz", "Стол офисный", price_kzt=41700)
    SupplierAgent.assess_budget([candidate], [Requirement("desk", "Стол офисный")], 100000)
    assert candidate.estimated_total_kzt is None
    assert candidate.budget_status == "unknown"


@pytest.mark.asyncio
async def test_documenter_maps_budget_and_method_without_changing_model(monkeypatch):
    agent = DocumenterAgent()
    async def reply(*args, **kwargs):
        return {"title": "Стол", "budget_kzt": 100000, "method": "request_quotes"}
    monkeypatch.setattr(agent, "_chat_json", reply)
    result = await agent.run("Поставка стола", lot_id="test")
    assert result.amount_kzt == 100000
    assert result.procurement_method == "request_quotes"
    assert result.technical_specification == "Поставка стола"


@pytest.mark.asyncio
async def test_sandbox_keeps_rejected_candidate_in_trace_only(monkeypatch):
    from app.api import sandbox
    from app.core.supabase_auth import SupabaseUser
    from app.db import Base
    from app.db import models  # noqa: F401
    bad = SupplierCandidate("Wrong desk", "test.kz", "Стол 1500 мм")
    bad.requirement_matches = [{"code": "desk", "status": "no"}]
    unknown = SupplierCandidate("Unconfirmed desk", "other.kz", "Стол")
    unknown.requirement_matches = [{"code": "desk", "status": "unknown"}]
    good = SupplierCandidate("Supported desk", "good.kz", "Стол")
    good.requirement_matches = [{"code": "desk", "status": "partial"}]
    class TestAgent:
        async def find_suppliers(self, *args, **kwargs):
            return [bad, unknown, good], Costs(), {"candidates_count": 3}
        async def match_requirements(self, *args):
            return Costs()
        assess_budget = staticmethod(SupplierAgent.assess_budget)
        summarize_lot_budget = staticmethod(SupplierAgent.summarize_lot_budget)
    monkeypatch.setattr(sandbox, "SupplierAgent", TestAgent)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await sandbox.run_supplier_sandbox(
                sandbox.SandboxRequest(lot_id="test", use_company_profile=False, limit=1,
                    requirements=[{"code": "desk", "title": "Стол", "is_mandatory": True}]),
                SupabaseUser("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "test@example.invalid"), session)
        assert [c["supplier"] for c in result["candidates"]] == ["Supported desk"]
        assert result["rejected_candidates"][0]["supplier"] == "Wrong desk"
        assert result["trace"]["filtered_out"]["dropped_mandatory"] == 1
        assert result["trace"]["filtered_out"]["dropped_unconfirmed"] == 1
    finally:
        await engine.dispose()


@pytest.mark.parametrize("price", [0, -1, "NaN", "Infinity", "not-a-price"])
def test_browser_invalid_price_does_not_overwrite_verified_price(price):
    candidate = SupplierCandidate("Test", "test.kz", "Стол", price_kzt=41700)
    SupplierAgent._merge_browser_output(candidate, {"price_kzt": price})
    assert candidate.price_kzt == 41700
