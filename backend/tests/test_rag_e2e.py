"""End-to-end smoke: Legal Agent с реальным RAG (закон проиндексирован в Qdrant).

Если Qdrant не запущен или RAG пуст — тест выводит предупреждение и завершается
с кодом 0 (не падает). Для полноценной проверки запустите Qdrant через
`docker compose up -d` и проиндексируйте закон `python -m app.rag.indexer ...`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.legal import LegalAgent  # noqa: E402
from app.rag import RAGStore  # noqa: E402

SAMPLE_TZ = """
ЛОТ № 5551234
Заказчик: ТОО «СтройМонтаж», БИН 050555000123
Способ: конкурс
Бюджет: 25 000 000 тенге

Поставка строительных материалов:
- Цемент М500 — 200 тонн
- Песок мытый — 500 тонн

Требования:
- Опыт работы не менее 15 лет
- Наличие собственного автопарка (не менее 20 единиц)
- Поставщик должен быть резидентом Алматинской области не менее 10 лет
"""


async def main() -> None:
    print("=== RAG Store check ===")
    store = RAGStore(collection="law_kz")
    n = store.count()
    print(f"Чанков в коллекции: {n}")
    if n == 0:
        print(
            "\n⚠ RAG пуст (Qdrant не запущен или коллекция не проиндексирована). "
            "Тест завершается без assertion. Для полноценной проверки:\n"
            "  1. docker compose up -d  (поднимет Qdrant)\n"
            "  2. python -m app.rag.indexer ../data/raw/law_kz --collection law_kz"
        )
        return

    print("\n=== Поиск в RAG по запросу 'требования к поставщику' ===")
    hits = await store.search("требования к опыту работы поставщика", top_k=3)
    for h in hits:
        print(f"  score={h.score:.3f}: {h.chunk.text[:120]}...")

    print("\n=== Legal Agent (с RAG) ===")
    legal = LegalAgent(rag=store)
    r = await legal.run(SAMPLE_TZ, lot_id="5551234")
    # Поддерживаем оба варианта имени поля: items (старое) и checks (новое)
    items = getattr(r, "items", None) or getattr(r, "checks", None) or []
    print(f"Overall risk: {r.overall_risk}, items: {len(items)}")
    print(f"Summary: {getattr(r, 'summary', '')}")
    print()
    for it in items:
        # Поля также имеют несколько имён для совместимости
        ref = (
            getattr(it, "law_reference", None)
            or getattr(it, "rule_id", None)
            or ""
        )
        rule_title = (
            getattr(it, "rule_title", None)
            or getattr(it, "title", None)
            or ""
        )
        status = getattr(it, "status", "") or getattr(it, "severity", "")
        print(f"  [{status}/{it.severity}] {rule_title} [{ref}]")
        print(f"    {it.description[:200]}")
    draft = getattr(r, "complaint_draft", None)
    if draft:
        if isinstance(draft, dict):
            import json as _json

            print(
                f"\n=== Complaint draft (dict) ===\n{_json.dumps(draft, ensure_ascii=False, indent=2)}"
            )
        else:
            print(f"\n=== Complaint draft (first 400 chars) ===\n{str(draft)[:400]}")
    print("\n✅ End-to-end test passed")


if __name__ == "__main__":
    asyncio.run(main())
