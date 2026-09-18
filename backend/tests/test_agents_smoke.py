"""Smoke-тест агентов на синтетическом ТЗ.

Запуск:
    cd tendr && python -m backend.tests.test_agents_smoke

Требует рабочий LLM_API_KEY (alemLLM или Mistral) в .env.
Если LLM недоступен — тест выводит предупреждение, но не падает
(проверяется только структура ответа, а не содержимое).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# корень проекта → backend/
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.documenter import DocumenterAgent  # noqa: E402
from app.agents.legal import LegalAgent  # noqa: E402

SAMPLE_TZ = """
ЛОТ № 9876543
Заказчик: ГКП «Городская поликлиника №7», БИН 123456789012
Способ закупки: конкурс
Бюджет: 8 500 000 тенге

ТЕХНИЧЕСКОЕ ЗАДАНИЕ
Поставка компьютерного оборудования.

1. Требования к поставщику:
- Опыт работы не менее 10 лет
- Собственный офис в Алматы ≥200 кв.м.
- Сертификат HP Gold Partner
- Минимум 50 отзывов на zakupki.kz
- Регистрация в РК не позднее 2005 года

2. Товар: системный блок (Intel i7-12700, 32ГБ RAM, SSD 1ТБ), мониторы 24", МФУ.
3. Гарантия 5 лет, доставка 3 рабочих дня.
4. Оплата 100% по факту поставки.
"""


async def main() -> None:
    print("=== Documenter Agent ===")
    doc = DocumenterAgent()
    a = await doc.run(SAMPLE_TZ, lot_id="9876543")
    print(f"Title: {a.title}")
    print(f"Requirements: {len(a.requirements)}, Red flags: {len(a.red_flags)}")
    for f in a.red_flags:
        print(f"  ⚠ {f[:100]}")

    # Если LLM не отработал (title = "(не удалось проанализировать)") —
    # пропускаем assertion про red_flags, но проверяем структуру ответа.
    llm_worked = a.title and not a.title.startswith("(не удалось")
    if llm_worked:
        assert len(a.red_flags) >= 1, "Должен найти хотя бы один red flag"
    else:
        print("\n⚠ LLM недоступен — assertion про red_flags пропущен")

    print("\n=== Legal Agent ===")
    legal = LegalAgent()
    r = await legal.run(SAMPLE_TZ, lot_id="9876543")
    # Поддерживаем оба варианта имени поля: items (старое) и checks (новое).
    items = getattr(r, "items", None) or getattr(r, "checks", None) or []
    print(f"Overall risk: {r.overall_risk}, items: {len(items)}")
    assert r.overall_risk in {"low", "medium", "high", "needs_review"}
    print("\n✅ Smoke-test passed")


if __name__ == "__main__":
    asyncio.run(main())
