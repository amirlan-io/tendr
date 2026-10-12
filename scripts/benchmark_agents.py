"""Read-only live agent benchmark using configured providers and isolated SQLite.

Run with the project's Python environment: python scripts/benchmark_agents.py
Calls real LLM/search services; browser tasks and outgoing contacts are disabled.
Use --output for the report path and --case to repeat selected scenarios.
"""

import asyncio
import argparse
import os
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from loguru import logger
logger.remove()
from app.core.config import get_settings
from app.agents.documenter import DocumenterAgent
from app.agents.product_search import ProductSearchAgent
from app.schemas.lot import ProductSearchRequest
from app.api.sandbox import SandboxRequest, run_supplier_sandbox
from app.core.supabase_auth import SupabaseUser
from app.db import Base
from app.db import models
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.llm import close_llm

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=ROOT / 'docs' / 'agent-benchmark-latest.json')
parser.add_argument('--anymodel-model', help='Exact model id from AnyModel catalog')
parser.add_argument('--api-key-file', type=Path, help='Private key file; alternatively ANYMODEL_API_KEY')
parser.add_argument('--case', action='append', dest='cases', help='Run only this named scenario (repeatable)')
args = parser.parse_args()
OUT = args.output

TZ = '''ТЕСТОВОЕ ТЗ, не реальная закупка. Заказчик: Тестовая компания.
Бюджет: 100 000 тенге. Поставка 2 офисных столов в Астану.
Обязательные требования:
1. Размер столешницы 1400х700 мм.
2. Высота 750 мм.
3. Материал столешницы ЛДСП толщиной 25 мм.
4. Металлический каркас.
5. Гарантия 24 месяца.
6. Доставка и сборка включены в стоимость, в течение 10 календарных дней.
7. Сертификат соответствия приложить к заявке.
Оплата в течение 30 календарных дней после приёмки. Новые товары.
'''

async def main():
    settings = get_settings()
    # Read-only search; paid remote browser is outside this benchmark.
    settings.browser_use_api_key = ''
    model = settings.llm_model
    if args.anymodel_model:
        from app.llm import mistral as factory
        from app.llm.openai_compat import OpenAICompatProvider
        key = args.api_key_file.read_text().strip() if args.api_key_file else os.environ.get('ANYMODEL_API_KEY', '')
        if not key:
            raise RuntimeError('Set ANYMODEL_API_KEY or --api-key-file')
        model = args.anymodel_model
        factory._provider = OpenAICompatProvider(api_key=key, base_url='https://anymodel.org/v1', model=model)

    report = {'base_commit': '95dd0b0', 'local_code_fixes': True, 'model': model,
              'scope': 'synthetic specifications, real LLM/Tavily/pages, isolated SQLite, no saved shortlist or outreach',
              'runs': []}
    def save():
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    async def record(name, fn):
        if args.cases and name not in args.cases:
            return
        print('START ' + name, flush=True)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(fn(), timeout=300)
            result = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
            row = {'name': name, 'seconds': round(time.monotonic()-started, 1), 'result': result}
            if isinstance(result, dict):
                print(json.dumps({'name': name, 'seconds': row['seconds'], 'total': result.get('total'),
                                  'requirements': len(result.get('requirements', [])),
                                  'products': len(result.get('products', [])),
                                  'title': result.get('title'), 'summary': result.get('summary')}, ensure_ascii=False), flush=True)
        except Exception as exc:
            row = {'name': name, 'seconds': round(time.monotonic()-started,1), 'error_type': type(exc).__name__}
            print(json.dumps(row), flush=True)
        report['runs'].append(row)
        save()

    await record('documenter_office_requirements', lambda: DocumenterAgent().run(TZ, lot_id='benchmark-office'))
    seven_goods = '''Заказчик: Тестовая компания. Бюджет 1000000 тенге.
Поставка в Астану в течение 10 дней. Оплата через 30 дней после приёмки.
1. Ноутбук: RAM 16 ГБ, SSD 512 ГБ, экран 15,6 дюйма. Количество 4 шт.
2. Монитор: IPS, диагональ 24 дюйма, HDMI. Количество 4 шт.
3. Принтер: лазерный, A4, двусторонняя печать. Количество 2 шт.
4. ИБП: 1000 ВА, USB. Количество 3 шт.
5. Коммутатор: 24 порта Gigabit Ethernet. Количество 1 шт.
6. Проектор: яркость 3500 люмен, Full HD. Количество 1 шт.
7. Сканер: A4, автоподача 50 листов. Количество 2 шт.
К заявке приложить сертификат соответствия.'''
    await record('documenter_seven_products', lambda: DocumenterAgent().run(seven_goods, lot_id='benchmark-seven'))
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user = SupabaseUser(id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', email='benchmark@example.invalid')
    async def sandbox(requirements, budget, regions):
        async with maker() as session:
            return await run_supplier_sandbox(
                SandboxRequest(lot_id='benchmark-synthetic', requirements=requirements,
                               budget_kzt=budget, regions=regions, query_variants=1, limit=5,
                               use_company_profile=False, enrich_browser=True,
                               page_fetch_top_n=5, save_results=False), user, session)
    await record('sandbox_office_desks', lambda: sandbox([
        {'code':'desk','title':'Стол офисный','description':'Размер 1400х700 мм, высота 750 мм, ЛДСП 25 мм, металлический каркас, гарантия 24 месяца. Количество 2 шт.','is_mandatory':True}
    ], 100000, ['Астана']))
    await record('sandbox_filter_and_regulator', lambda: sandbox([
        {'code':'filter','title':'Топливный фильтр','description':'Для ДВС легкового автомобиля. Количество 10 шт.','is_mandatory':True},
        {'code':'regulator','title':'Регулятор давления','description':'Стальной, фланцевый, проход 80 мм, давление 60,3 МПа. Количество 1 шт.','is_mandatory':True}
    ], 48000, []))
    await record('sandbox_exact_filter', lambda: sandbox([
        {'code':'filter','title':'Топливный фильтр 13592436',
         'description':'Для Chevrolet Cobalt 2014, тип топливный фильтр, OEM 13592336. Количество 10 шт.',
         'is_mandatory':True}
    ], 48000, ['Астана']))
    await record('product_search_office_desks', lambda: ProductSearchAgent().run(ProductSearchRequest(
        query='Стол офисный 1400х700 мм Астана', budget_kzt=100000, quantity=2,
        additional_info='Общий бюджет на два стола 100000 тенге. ЛДСП 25 мм, металлический каркас, высота 750 мм, гарантия 24 месяца.'),lot_id='benchmark-office'))
    from app.agents.supplier_agent import SupplierAgent, SupplierCandidate, Requirement
    async def confirmed_page():
        agent = SupplierAgent()
        candidate = SupplierCandidate('Арлан', 'arlanstyle.kz', 'Стол письменный 1500*700*750',
            url='https://arlanstyle.kz/p23539093-stol-pismennyj-1500700750.html')
        costs = await agent.enrich_with_pages([candidate], terms=['Стол письменный', 'Стол офисный'])
        requirements = [Requirement('desk', 'Стол письменный',
            'Размер 1500х700 мм, высота 750 мм, ЛДСП 16 мм, опоры ЛДСП. Количество 2 шт.', True)]
        await agent.match_requirements([candidate], requirements)
        agent.assess_budget([candidate], requirements, 100000)
        return {'card': candidate.to_card(), 'match': candidate.to_match(), 'pages_read':costs.page_fetch_count}
    await record('known_product_page_positive_control', confirmed_page)
    async def kaspi_filter_control():
        agent = SupplierAgent()
        candidate = SupplierCandidate('Kaspi', 'kaspi.kz', 'Топливный фильтр 13592436',
            url='https://kaspi.kz/shop/p/toplivnyi-fil-tr-13592436-108443317')
        requirements = [Requirement('filter', 'Топливный фильтр',
            'Для Chevrolet Cobalt 2014, тип топливный фильтр, OEM 13592336. Количество 10 шт.', True)]
        costs = await agent.enrich_with_pages([candidate], top_n=1,
            terms=['Топливный фильтр'], region_hint='Астана')
        match_costs = await agent.match_requirements([candidate], requirements)
        agent.assess_budget([candidate], requirements, 48000)
        return {'card': candidate.to_card(), 'match': candidate.to_match(),
                'evidence_text': candidate.evidence_text,
                'pages_read': costs.page_fetch_count, 'llm_calls': match_costs.llm_calls}
    await record('known_kaspi_filter_browser_control', kaspi_filter_control)
    await engine.dispose()
    await close_llm()
    print('REPORT '+str(OUT), flush=True)

asyncio.run(main())
