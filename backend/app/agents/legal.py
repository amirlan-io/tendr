"""Legal Agent: проверка соответствия Закону РК «О госзакупках» + жалобы.

Философия: лоялен к мелочам, строг к реальным нарушениям.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.rag import RAGStore
from app.schemas.lot import (
    LegalCheckItem,
    LegalCheckResult,
)


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


class LegalAgent(Agent):
    """Проверяет лот на соответствие Закону РК «О государственных закупках»
    с опорой на RAG-индекс по нормативной базе.

    Коллекция RAG: "law_kz" — должна быть предварительно наполнена
    текстами закона, приказов МФ, реестра типовых ТЗ.
    """

    name = "legal"

    system_prompt = """Ты — юрист-эксперт по государственным закупкам Республики Казахстан.
Твоя задача — проверить техническое задание лота на соответствие
Закону РК «О государственных закупках» и подзаконным актам.

Тебе будет дано ТЗ лота и выдержки из нормативной базы.
Верни СТРОГО валидный JSON:
{
  "items": [
    {"rule_id": "...", "rule_title": "...",
     "status": "ok|violation|risk|needs_review",
     "severity": "low|medium|high",
     "description": "...",
     "law_reference": "статья/пункт закона",
     "recommendation": "что делать"}
  ],
  "overall_risk": "low|medium|high",
  "summary": "краткое резюме проверки в 2-3 предложениях",
  "can_complain_to_counting_committee": true/false,
  "complaint_draft": "если есть нарушения и нужно подавать жалобу — черновик жалобы в Счётный комитет на госязыке или русском, иначе null"
}

ПРИНЦИПЫ РАБОТЫ:

1. ЛОЯЛЬНОСТЬ К МЕЛОЧАМ.
   Не будь занудой. Если нарушение мелкое, формальное, типовое для отрасли,
   или заказчик его легко исправит — НЕ вноси его в список.
   Лучше меньше нарушений, но все будут серьёзные.
   Сосредоточься только на том, что реально мешает участнику.

2. СТРОГОСТЬ К РЕАЛЬНЫМ ПРОБЛЕМАМ.
   Грубые нарушения — обязательно фиксируй:
   - дискриминационные требования (опыт работы с конкретным поставщиком,
     требование быть резидентом определённого региона без обоснования,
     избыточные квалификационные требования)
   - завышенные требования (например, требуется 5 лет опыта для лота на 1 млн тг)
   - отсутствие бюджета, сроков, существенных условий
   - противоречие антимонопольному законодательству
   - требование документов, не предусмотренных Законом

3. СОМНЕВАЕШЬСЯ — ПРОПУСТИ.
   Если не уверен в нарушении — НЕ вноси его.
   Лучше ничего не написать, чем ошибочно обвинить заказчика.
   Помечай status=needs_review ТОЛЬКО когда явно нужно участие юриста-человека.

4. ЖАЛОБУ ПИШИ ТОЛЬКО ПРИ СЕРЬЁЗНЫХ НАРУШЕНИЯХ.
   complaint_draft генерируй ТОЛЬКО если есть хотя бы один item
   со status=violation и severity=high, иначе null.
   Имитация жалоб без оснований — отвлекает от реальных проблем.

5. НЕ ВЫДУМЫВАЙ СТАТЬИ.
   Ссылайся только на те нормы, которые реально упомянуты
   в RAG-контексте или в самом ТЗ.

6. ФОРМА ЖАЛОБЫ (если complaint_draft не null):
   - шапка: Счётный комитет по контролю за осуществлением госзакупок РК
   - обстоятельства: краткое описание лота и выявленных нарушений
   - нарушенные нормы: конкретные статьи Закона с номерами
   - просительная часть: признать, обязать устранить, приостановить
"""

    def __init__(self, rag: RAGStore | None = None) -> None:
        self.rag = rag or RAGStore(collection="law_kz")

    async def run(self, lot_text: str, *, lot_id: str) -> LegalCheckResult:
        # 1. ищем релевантные нормы в RAG
        context_chunks: list[str] = []
        if self.rag.count() > 0:
            query = (
                f"Проверка соответствия государственных закупок требованиям Закона РК. "
                f"Лот: {lot_text[:500]}"
            )
            hits = await self.rag.search(query, top_k=6)
            context_chunks = [h.chunk.text for h in hits]

        context_block = "\n\n---\n\n".join(context_chunks) if context_chunks else "(RAG пуст)"
        prompt = (
            f"ID лота: {lot_id}\n\n"
            f"Техническое задание:\n```\n{lot_text[:10000]}\n```\n\n"
            f"Нормативная база (RAG):\n```\n{context_block[:4000]}\n```\n\n"
            "Проведи проверку и верни JSON."
        )
        data = await self._chat_json(prompt, max_tokens=5000)
        if not data:
            return LegalCheckResult(
                lot_id=lot_id,
                items=[],
                overall_risk="needs_review",
                summary="Не удалось выполнить проверку. Попробуйте позже.",
            )

        items = [
            LegalCheckItem(
                # Поддерживаем оба варианта полей от LLM
                category=_s(it.get("category") or it.get("rule_id") or "general"),
                title=_s(it.get("title") or it.get("rule_title") or ""),
                severity=_s(it.get("severity"), "info"),
                status=_s(it.get("status"), "info"),
                description=_s(it.get("description") or ""),
                recommendation=_s(it.get("recommendation") or ""),
                rule_id=_s(it.get("rule_id")) or None,
                rule_title=_s(it.get("rule_title")) or None,
                law_reference=_s(it.get("law_reference")) or None,
            )
            for it in data.get("items", [])
        ]
        return LegalCheckResult(
            lot_id=lot_id,
            # Заполняем оба поля — checks (новое имя) и items (alias для совместимости)
            checks=items,
            items=items,
            overall_risk=_s(data.get("overall_risk"), "needs_review"),
            summary=_s(data.get("summary")),
            can_complain_to_counting_committee=bool(
                data.get("can_complain_to_counting_committee", False)
            ),
            complaint_draft=data.get("complaint_draft"),
        )
