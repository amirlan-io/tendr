"""No external services: exercise verification-triggered recovery end to end."""
from types import SimpleNamespace

import pytest

from app.agents import supplier_agent as module
from app.agents.supplier_agent import SupplierAgent, SupplierCandidate, Requirement, Costs


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_retry', [False, True])
async def test_wrong_local_card_triggers_reserved_search(monkeypatch, failed_retry):
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(
        supplier_search_max_calls=3, tavily_api_key='', browser_use_api_key=''))
    agent = SupplierAgent()
    calls, matched = [], []
    reqs = [Requirement('f', 'Топливный фильтр', 'Количество 10 шт.'),
            Requirement('r', 'Регулятор давления', '80 мм 60,3 МПа. Количество 1 шт.')]

    def search(**kwargs):
        query = kwargs['query']
        calls.append(query)
        if len(calls) == 3 and failed_retry:
            raise RuntimeError('Search unavailable')
        code = 'filter' if 'фильтр' in query else ('good' if len(calls) == 3 else 'wrong')
        title = 'Топливный фильтр' if code == 'filter' else 'Регулятор давления'
        return {'results': [{'url': f'https://shop.kz/product/{code}',
                             'title': title, 'content': title, 'score': .9}]}

    async def pages(cards, **kwargs):
        for c in cards:
            c.price_kzt = 100
            c.sources['price'] = c.url
        return Costs()

    async def match(cards, requirements):
        for c in cards:
            matched.append(c.url)
            c.requirement_matches = [{'code': r.code, 'status': (
                'fits' if (r.code == 'f' and c.url.endswith('filter'))
                or (r.code == 'r' and c.url.endswith('good')) else 'no')}
                for r in requirements]
        return Costs()

    agent._tavily_client = SimpleNamespace(search=search)
    monkeypatch.setattr(agent, 'enrich_with_pages', pages)
    monkeypatch.setattr(agent, 'match_requirements', match)
    cards, costs, meta = await agent.find_suppliers(reqs, budget_kzt=5000, allow_browser_fallback=False)
    assert costs.tavily_calls == len(calls) == 3
    assert meta['reserved_search_calls'] == 1
    assert meta['recovery_queries'][0]['code'] == 'r'
    assert '60,3' in calls[2]
    assert len(matched) == len(set(matched))  # no repeat LLM checks or budget penalties
    assert meta['missing_product_codes'] == (['r'] if failed_retry else [])
    summary = agent.summarize_lot_budget(cards, reqs, 5000)
    assert summary['selected_goods_kzt'] == (None if failed_retry else 1100)


def test_gap_reasons_require_verified_price():
    req = Requirement('f', 'Топливный фильтр')
    candidate = SupplierCandidate('Shop', 'shop.kz', req.title, url='https://shop.kz/product/f')
    gaps = lambda cards: SupplierAgent.verification_gaps(cards, [req])[0]['status']
    assert gaps([]) == 'not_found'
    assert gaps([candidate]) == 'specs_unconfirmed'
    candidate.requirement_matches = [{'code': 'f', 'status': 'fits'}]
    candidate.price_kzt = 10
    assert gaps([candidate]) == 'price_missing'
    candidate.sources['price'] = candidate.url
    assert gaps([candidate]) == 'ready'
    candidate.budget_status = 'over_budget'
    assert gaps([candidate]) == 'over_budget'

@pytest.mark.asyncio
@pytest.mark.parametrize('limit,ready', [(0, False), (1, False), (4, True), (4, False)])
async def test_recovery_respects_budget_dedup_and_blocklist(monkeypatch, limit, ready):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(
        supplier_search_max_calls=limit, tavily_api_key='', browser_use_api_key=''))
    agent = SupplierAgent()
    req = Requirement('f', 'Топливный фильтр', 'Количество 1 шт.')
    card = SupplierCandidate('Shop', 'shop.kz', req.title, url='https://shop.kz/product/f')
    if ready:
        card.requirement_matches = [{'code': 'f', 'status': 'fits'}]
        card.price_kzt = 100
        card.sources['price'] = card.url
    calls = []
    def search(**kwargs):
        calls.append(kwargs)
        return {'results': [
            {'url': card.url + '/', 'title': req.title},
            {'url': 'https://blocked.kz/product/f', 'title': req.title},
        ]}
    agent._tavily_client = SimpleNamespace(search=search)
    agent.match_requirements = AsyncMock(return_value=Costs())
    agent.enrich_with_pages = AsyncMock(return_value=Costs())
    costs = Costs(tavily_calls=1)
    meta = {'search_call_limit': limit, 'queries': [], 'direct_queries': [], 'blocked_filtered': 0}
    cards = [card]
    await agent.recover_unresolved(cards, [req], costs, meta, blocked={'blocked.kz'})
    assert len(calls) == (1 if limit > 1 and not ready else 0)
    assert cards == [card]
    agent.match_requirements.assert_not_awaited()
    agent.enrich_with_pages.assert_not_awaited()


def test_shortlist_preserves_each_position_and_prefers_confirmed_price():
    from app.api.sandbox import _select_shortlist
    reqs = [Requirement('f', 'Топливный фильтр'), Requirement('r', 'Регулятор давления')]
    cards = []
    for i, code in enumerate(['f', 'f', 'f', 'r']):
        c = SupplierCandidate('Shop', 'shop.kz', code, url=f'https://shop.kz/product/{i}')
        c.score = 90 if code == 'f' else 50
        c.requirement_matches = [{'code': code, 'status': 'fits'}]
        cards.append(c)
    cards[2].price_kzt = 100
    cards[2].sources['price'] = cards[2].url
    assert _select_shortlist(cards, reqs, 2) == [cards[2], cards[3]]

@pytest.mark.asyncio
async def test_tied_gaps_prioritize_undersearched_item_and_open_web(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(
        supplier_search_max_calls=4, tavily_api_key='', browser_use_api_key=''))
    agent = SupplierAgent()
    agent._tavily_client = object()
    reqs = [Requirement('f', 'Топливный фильтр'), Requirement('r', 'Регулятор давления', '60,3 МПа')]
    agent.search_web = AsyncMock(return_value=([], Costs(tavily_calls=1)))
    meta = {'search_call_limit': 4, 'queries': [], 'direct_queries': [],
            'search_attempts_by_code': {'f': 2, 'r': 1}, 'blocked_filtered': 0}
    await agent.recover_unresolved([], reqs, Costs(tavily_calls=3), meta)
    assert [q['code'] for q in meta['recovery_queries']] == ['r']
    assert agent.search_web.await_args.kwargs['domains'] is None
    assert '60,3' in agent.search_web.await_args.args[0][0]

@pytest.mark.asyncio
async def test_open_web_financial_regulator_is_not_a_product(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(
        supplier_search_max_calls=1, tavily_api_key='', browser_use_api_key=''))
    agent = SupplierAgent()
    agent._tavily_client = object()
    agent.search_web = AsyncMock(return_value=([
        {'title': 'Регулятор не будет защищать инвесторов мемкоина',
         'url': 'https://news.example/news/regulator', 'content': 'США SEC'}], Costs(tavily_calls=1)))
    agent.enrich_with_pages = AsyncMock()
    agent.match_requirements = AsyncMock()
    cards = []
    meta = {'search_call_limit': 1, 'queries': [], 'direct_queries': [], 'blocked_filtered': 0}
    await agent.recover_unresolved(cards, [Requirement('r', 'Регулятор давления')], Costs(), meta)
    assert cards == []
    agent.enrich_with_pages.assert_not_awaited()
    agent.match_requirements.assert_not_awaited()
