"""Compare AnyModel routes on the same document and the same verified product page.

Only reads public web pages and writes a local report. The key stays outside
the repository: pass --api-key-file with a private file.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger
logger.remove()

from app.agents.documenter import DocumenterAgent
from app.agents.supplier_agent import Requirement, SupplierAgent, SupplierCandidate
from app.llm import mistral as llm_factory
from app.llm.openai_compat import OpenAICompatProvider

DOCUMENT = """Заказчик: Тестовая компания. Бюджет 1000000 тенге.
Поставка в Астану в течение 10 дней. Оплата через 30 дней после приёмки.
1. Ноутбук: RAM 16 ГБ, SSD 512 ГБ, экран 15,6 дюйма. Количество 4 шт.
2. Монитор: IPS, диагональ 24 дюйма, HDMI. Количество 4 шт.
3. Принтер: лазерный, A4, двусторонняя печать. Количество 2 шт.
4. ИБП: 1000 ВА, USB. Количество 3 шт.
5. Коммутатор: 24 порта Gigabit Ethernet. Количество 1 шт.
6. Проектор: яркость 3500 люмен, Full HD. Количество 1 шт.
7. Сканер: A4, автоподача 50 листов. Количество 2 шт.
К заявке приложить сертификат соответствия."""

PRODUCT_URL = "https://arlanstyle.kz/p23539093-stol-pismennyj-1500700750.html"
EXPECTED_QUANTITIES = [4, 4, 2, 3, 1, 1, 2]
REQUIREMENTS = [
    Requirement("matching_desk", "Стол письменный", "Размер 1500х700 мм, высота 750 мм, ЛДСП 16 мм, опоры ЛДСП. Количество 2 шт.", True),
    Requirement("wrong_desk", "Стол письменный", "Размер 1400х700 мм, высота 750 мм, ЛДСП 25 мм, металлический каркас. Количество 2 шт.", True),
    Requirement("warranty_unknown", "Стол письменный", "Размер 1500х700 мм, ЛДСП 16 мм, гарантия 24 месяца. Количество 2 шт.", True),
]
EXPECTED_STATUSES = {"matching_desk": "fits", "wrong_desk": "no", "warranty_unknown": "partial"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="append", required=True)
    return parser.parse_args()


async def main():
    args = parse_args()
    key = args.api_key_file.read_text().strip()
    if not key:
        raise RuntimeError("Empty API key file")

    source_agent = SupplierAgent()
    source = SupplierCandidate("Арлан", "arlanstyle.kz", "Стол письменный 1500*700*750", url=PRODUCT_URL)
    page_costs = await source_agent.enrich_with_pages([source], terms=["Стол письменный"])
    if not source.evidence_text or page_costs.page_fetch_count != 1:
        raise RuntimeError("The known product page could not be read; no fair model comparison is possible")

    report = {
        "purpose": "paired model comparison on a synthetic seven-item specification and one live product page",
        "document_sha256": hashlib.sha256(DOCUMENT.encode()).hexdigest(),
        "source_url": PRODUCT_URL,
        "source_sha256": hashlib.sha256(source.evidence_text.encode()).hexdigest(),
        "source_chars": len(source.evidence_text),
        "source_price_kzt": source.price_kzt,
        "expected_quantities": EXPECTED_QUANTITIES,
        "expected_match_statuses": EXPECTED_STATUSES,
        "models": [],
    }

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    save()
    for model_id in args.model:
        provider = OpenAICompatProvider(api_key=key, base_url="https://anymodel.org/v1", model=model_id)
        llm_factory._provider = provider
        started = time.monotonic()
        row = {"model": model_id}
        print("START " + model_id, flush=True)
        try:
            analysis = await asyncio.wait_for(DocumenterAgent().run(DOCUMENT, lot_id="model-comparison"), timeout=180)
            quote_count = sum(bool(req.source_quote) and req.source_quote in DOCUMENT for req in analysis.requirements)
            quantities = [req.quantity for req in analysis.requirements]
            row["document"] = {
                "title": analysis.title,
                "positions": len(analysis.requirements),
                "names": [req.name for req in analysis.requirements],
                "quantities": quantities,
                "quotes_verified": quote_count,
                "documents": analysis.documents_required,
                "warnings": analysis.warnings,
                "pass": len(analysis.requirements) == 7 and quantities == EXPECTED_QUANTITIES and quote_count == 7,
            }
            candidate = SupplierCandidate("Арлан", "arlanstyle.kz", source.title, url=PRODUCT_URL,
                                          price_kzt=source.price_kzt, evidence_text=source.evidence_text)
            await asyncio.wait_for(SupplierAgent().match_requirements([candidate], REQUIREMENTS), timeout=180)
            statuses = {match["code"]: match["status"] for match in candidate.requirement_matches}
            row["matching"] = {
                "statuses": statuses,
                "comments": {match["code"]: match.get("comment", "") for match in candidate.requirement_matches},
                "pass": statuses == EXPECTED_STATUSES,
            }
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            row["error_summary"] = str(exc)[:160].replace(key, "[redacted]")
        finally:
            row["seconds"] = round(time.monotonic() - started, 1)
            report["models"].append(row)
            save()
            await provider.close()
            llm_factory._provider = None
            print(json.dumps({"model": model_id, "seconds": row["seconds"],
                              "document_pass": row.get("document", {}).get("pass"),
                              "matching_pass": row.get("matching", {}).get("pass"),
                              "error_type": row.get("error_type")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
