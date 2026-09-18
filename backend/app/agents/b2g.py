"""B2G Agent: помощь заказчикам с подготовкой ТЗ для госзакупок.

На вход: текстовое описание потребности ("Хотим закупить 100 парт в школу")
На выход:
- Готовое техническое задание (техническая спецификация)
- Проверка на дискриминационные требования
- Прогноз рыночной цены (на основе похожих лотов из БД)
- Чек-лист обязательных полей по Закону РК
- Шаблон контракта (если запросили)

Использует RAG-индекс по закону (как Legal Agent),
но акцент на статьях 9-15 Закона РК (требования к ТЗ заказчика).
"""

from __future__ import annotations

from app.agents.base import Agent
from app.rag import RAGStore
from app.schemas.lot import B2GRequest, B2GResult


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


class B2GAgent(Agent):
    """Помогает заказчикам (государственным органам, квазигоссектору)
    составить корректное ТЗ для объявления госзакупки.

    Коллекция RAG: "law_kz" — та же, что у Legal Agent.
    """

    name = "b2g"

    system_prompt = """Ты — эксперт по подготовке технических заданий для государственных закупок
Республики Казахстан. Твоя задача — помочь заказчику (акимату, школе, больнице,
квазигоссектору) составить корректное ТЗ, которое:

1. Соответствует Закону РК «О государственных закупках» (ст. 9-15).
2. НЕ содержит дискриминационных требований.
3. Содержит все обязательные поля.
4. Реалистично по цене (на основе рыночных данных).

Тебе будет дано:
- Описание потребности заказчика (что хочет закупить, для кого, зачем)
- Исторические данные по похожим лотам (если есть)
- Выдержки из закона

Верни СТРОГО валидный JSON:
{
  "title": "Краткое название лота",
  "description": "Развёрнутое описание предмета закупки (2-3 абзаца)",
  "technical_specification": "Подробная тех. спецификация (требования к товару/услуге, "
                            "количество, сроки, качество, гарантии)",
  "category": "товары|услуги|работы",
  "procurement_method": "tender|auction|request_quotes|single_source|other",
  "estimated_budget_kzt": 1234567,
  "deadline": "2026-08-15",
  "delivery_address": "г. Алматы, ул. ...",
  "delivery_days": 30,
  "qualification_requirements": [
    "Опыт работы не менее 3 лет",
    "Наличие лицензии",
    "..."
  ],
  "documents_required": [
    "Справка об отсутствии налоговой задолженности",
    "Копия устава",
    "..."
  ],
  "evaluation_criteria": {
    "price_weight": 70,
    "quality_weight": 30,
    "description": "Как оценивать заявки"
  },
  "red_flags": [
    "Требование опыта работы с конкретным поставщиком",
    "Указание товарного знака без 'или эквивалент'",
    "..."
  ],
  "warnings": [
    "Бюджет может быть завышен — проверьте по рынку",
    "Срок подачи слишком короткий — увеличьте до 10 дней"
  ],
  "legal_compliance": "ok|review|violation",
  "compliance_notes": "Всё в порядке, кроме пункта 5 — срок подачи заявок 5 дней, что меньше минимума по Закону (10 рабочих дней)"
}

ПРИНЦИПЫ РАБОТЫ:

1. Будь конкретным. Тех. спецификация — это не абстрактные пожелания, а измеримые
   требования: "стол письменный, 1200x600x750 мм, ЛДСП 16 мм, цвет — бук, 4 ящика".

2. Избегай дискриминации. НЕ включай:
   - требование опыта работы с конкретным поставщиком
   - требование быть из определённого региона (без обоснования)
   - избыточные квалификационные требования
   - указание товарного знака без «или эквивалент»
   - требование членства в СРО без необходимости

3. Проверяй закон. Используй статьи из RAG-контекста:
   - Ст. 9 — содержание ТЗ
   - Ст. 10 — требования к потенциальным поставщикам
   - Ст. 11 — квалификационные требования
   - Ст. 13 — сроки
   - Ст. 15 — способы закупок

4. Реалистичная цена. Если в RAG или в similar_lots есть похожие лоты —
   ориентируйся на среднюю цену. Не завышай.

5. Если данных мало — отмечай в warnings, не выдумывай.
"""

    def __init__(self, rag: RAGStore | None = None) -> None:
        self.rag = rag or RAGStore(collection="law_kz")

    async def run(self, request: B2GRequest, *, lot_id: str = "b2g") -> B2GResult:
        """Генерирует ТЗ на основе описания потребности.

        Args:
            request: описание потребности + контекст (категория, регион, etc.)
            lot_id: для логирования
        """
        # 1. RAG-поиск: статьи закона о ТЗ + похожие лоты
        context_chunks: list[str] = []
        if self.rag.count() > 0:
            query = (
                f"Требования к техническому заданию госзакупки. "
                f"Статьи 9-15 Закона РК. "
                f"Предмет: {request.need_description[:300]}"
            )
            hits = await self.rag.search(query, top_k=5)
            context_chunks = [h.chunk.text for h in hits]

        context_block = "\n\n---\n\n".join(context_chunks) if context_chunks else "(RAG пуст)"

        # 2. История похожих лотов
        similar_text = ""
        if request.similar_lots:
            similar_lines = ["\nПохожие лоты из истории (для оценки бюджета):"]
            for lot in request.similar_lots[:5]:
                similar_lines.append(
                    f"- {lot.get('title', '?')[:80]}: {lot.get('budget_kzt', '?')} тг"
                )
            similar_text = "\n".join(similar_lines)

        # 3. Сборка промпта
        prompt = (
            f"Запрос заказчика: {request.need_description}\n"
            f"Категория: {request.category or 'не указана'}\n"
            f"Регион: {request.region or 'не указан'}\n"
            f"Заказчик: {request.organization or 'не указан'}\n"
            f"{similar_text}\n\n"
            f"Нормативная база (RAG):\n```\n{context_block[:4000]}\n```\n\n"
            "Сгенерируй ТЗ и верни JSON."
        )

        data = await self._chat_json(prompt, max_tokens=6000)
        if not data:
            return B2GResult(
                lot_id=lot_id,
                title="(не удалось сгенерировать)",
                description=request.need_description,
                technical_specification="(LLM не вернула результат. Попробуйте позже.)",
                red_flags=[],
                warnings=["Не удалось сгенерировать ТЗ. Попробуйте уточнить запрос."],
                legal_compliance="review",
                compliance_notes="Автоматическая генерация не сработала. "
                "Обратитесь вручную или повторите попытку.",
            )

        return B2GResult(
            lot_id=lot_id,
            title=_s(data.get("title")),
            description=_s(data.get("description")),
            technical_specification=_s(data.get("technical_specification")),
            category=_s(data.get("category")),
            procurement_method=_s(data.get("procurement_method"), "tender"),
            estimated_budget_kzt=data.get("estimated_budget_kzt"),
            deadline=data.get("deadline"),
            delivery_address=_s(data.get("delivery_address")),
            delivery_days=data.get("delivery_days"),
            qualification_requirements=data.get("qualification_requirements") or [],
            documents_required=data.get("documents_required") or [],
            evaluation_criteria=data.get("evaluation_criteria") or {},
            red_flags=data.get("red_flags") or [],
            warnings=data.get("warnings") or [],
            legal_compliance=_s(data.get("legal_compliance"), "review"),
            compliance_notes=_s(data.get("compliance_notes")),
        )
