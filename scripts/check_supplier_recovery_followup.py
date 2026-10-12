"""One explicitly bounded live follow-up to a saved sandbox report; no DB writes."""
import argparse
import asyncio
import json
import sys
import time
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from loguru import logger
logger.remove()
from app.agents.supplier_agent import SupplierAgent, SupplierCandidate, Requirement, Costs
from app.core.config import get_settings
from app.llm import close_llm, mistral
from app.llm.openai_compat import OpenAICompatProvider

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--api-key-file', type=Path, required=True)
    args = parser.parse_args()
    prior = json.loads(args.input.read_text())['runs'][0]['result']
    get_settings().browser_use_api_key = ''
    mistral._provider = OpenAICompatProvider(
        api_key=args.api_key_file.read_text().strip(), base_url='https://anymodel.org/v1',
        model='ag/gemini-3.7-flash-low')
    agent = SupplierAgent()
    allowed = {f.name for f in fields(SupplierCandidate)}
    cards = [SupplierCandidate(**{k:v for k,v in c.items() if k in allowed})
             for c in prior['candidates'] + prior['rejected_candidates']]
    reqs = [Requirement(r['code'], r['title'], r.get('description') or '', r['mandatory'])
            for r in prior['requirements']]
    used = prior['costs']['tavily_calls']
    costs = Costs(tavily_calls=used)
    # Reuse prior verified decisions. Exactly one additional search attempt.
    meta = dict(prior['trace'], search_call_limit=used + 1,
                search_attempts_by_code={'filter': 3, 'regulator': 1})
    initial_urls = {c.url for c in cards}
    # Previous report can fill the global candidate cap; retain the best known
    # card of each type plus concrete product pages to leave room for new evidence.
    from app.agents.supplier_agent import source_page_rank
    cards.sort(key=lambda c: (source_page_rank(c.url), -c.score))
    cards = cards[:15]
    start = time.monotonic()
    try:
        await asyncio.wait_for(agent.recover_unresolved(
            cards, reqs, costs, meta, budget_kzt=48000, page_fetch_top_n=3), timeout=240)
        result = {'source_report': str(args.input), 'seconds': round(time.monotonic()-start, 1),
                  'additional_search_calls': costs.tavily_calls-used,
                  'recovery_queries': meta['recovery_queries'],
                  'verification_gaps': meta['verification_gaps'],
                  'new_candidates': [dict(c.to_card(), requirement_matches=c.requirement_matches)
                                     for c in cards if c.url not in initial_urls],
                  'budget_summary': agent.summarize_lot_budget(cards, reqs, 48000)}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({k:v for k,v in result.items() if k != 'new_candidates'}, ensure_ascii=False))
    finally:
        await close_llm()

asyncio.run(main())
