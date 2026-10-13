"""Legal Agent: проверка соответствия Закону РК «О госзакупках» + жалобы.

Философия: лоялен к мелочам, строг к реальным нарушениям.
"""

from __future__ import annotations

import asyncio
from datetime import date

from app.agents.base import Agent
from app.core.config import get_settings
from app.rag import RAGStore
from app.schemas.lot import (
    LegalCheckItem,
    LegalCheckResult,
)


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _source_url(metadata: dict) -> str:
    return _s(metadata.get("official_url") or metadata.get("source_url") or metadata.get("url"))


def _source_revision(metadata: dict) -> str:
    return _s(metadata.get("version") or metadata.get("revision") or metadata.get("legal_text_revision"))


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
     "status": "ok|risk|needs_review",
     "severity": "low|medium|high",
     "description": "...",
     "law_reference": "статья/пункт закона",
     "article": "статья/пункт закона",
     "source": "источник нормы",
     "quote": "цитата из нормы",
     "citation_url": "ссылка на источник",
     "recommendation": "что делать"}
  ],
  "overall_risk": "low|medium|high|needs_review",
  "summary": "краткое резюме проверки в 2-3 предложениях",
  "can_complain_to_counting_committee": false,
  "complaint_draft": null
}

ПРИНЦИПЫ РАБОТЫ:

1. НЕ ВЫДАВАЙ ОПРЕДЕЛЁННЫЙ ВЫВОД БЕЗ НОРМАТИВНОЙ БАЗЫ.
   Если RAG пуст или недоступен — не делай юридический вывод. Верни пустой items и overall_risk='needs_review'.

2. СОМНЕВАЕШЬСЯ — НЕ УТВЕРЖДАЙ.
   Если нет достаточной уверенности, используй status='risk' или 'needs_review'.
   Не утверждай, что есть нарушение, если это лишь возможный риск, который требует проверки.
   Формулы типа 'возможный риск, требуется проверка' лучше, чем ложное обвинение.

3. НЕ ВЫДУМЫВАЙ СТАТЬИ И ССЫЛКИ.
   Используй только те нормы, которые реально упомянуты в RAG-контексте или в ТЗ.
   Если источник неизвестен, оставляй поля source/article/citation_url пустыми.

4. ЖАЛОБУ НЕ ГЕНЕРИРОВАТЬ.
   Для жалоб и институционального адресата требуется отдельная профессиональная проверка с реальным регламентом уполномоченного органа.
   Поэтому complaint_draft всегда должен быть null, а can_complain_to_counting_committee — false.
"""

    def __init__(self, rag: RAGStore | None = None) -> None:
        self.rag = rag or RAGStore(collection="law_kz")

    async def run(self, lot_text: str, *, lot_id: str) -> LegalCheckResult:
        rag_count = await asyncio.to_thread(self.rag.count) if self.rag is not None else 0
        if rag_count == 0:
            return LegalCheckResult(
                lot_id=lot_id,
                checks=[],
                items=[],
                overall_risk="needs_review",
                summary=(
                    "Юридическая проверка недоступна: нормативная база (RAG) пуста или "
                    "недоступна. Сначала загрузите корпус законодательства и проверьте Qdrant."
                ),
                can_complain_to_counting_committee=False,
                complaint_draft=None,
                corpus_revision=None,
            )

        settings = get_settings()
        try:
            age = (date.today() - date.fromisoformat(settings.legal_corpus_reviewed_at)).days
            verified = settings.legal_corpus_verified and 0 <= age <= settings.legal_corpus_max_age_days
        except ValueError:
            verified = False
        if not verified:
            return LegalCheckResult(
                lot_id=lot_id,
                overall_risk="needs_review",
                summary="Нормативная база не проверена или устарела. Требуется проверка специалистом.",
            )

        context_chunks: list[str] = []
        query = (
            f"Проверка соответствия государственных закупок требованиям Закона РК. "
            f"Лот: {lot_text[:500]}"
        )
        hits = await self.rag.search(query, top_k=6)
        hits = [hit for hit in hits if hit.chunk.metadata.get("verified")
                and _source_url(hit.chunk.metadata).startswith("https://")
                and _source_revision(hit.chunk.metadata)]
        if not hits:
            return LegalCheckResult(
                lot_id=lot_id, overall_risk="needs_review",
                summary="В проверенном корпусе не найдены нормы для этой закупки.",
            )
        context_chunks = [
            f"Источник: {h.chunk.source}\n"
            f"URL: {_source_url(h.chunk.metadata)}\n"
            f"Редакция: {_source_revision(h.chunk.metadata)}\n"
            f"{h.chunk.text}" for h in hits
        ]

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

        items = []
        rejected = 0
        for it in data.get("items", []):
            quote = _s(it.get("quote") or it.get("law_quote"))
            citation_url = _s(it.get("citation_url"))
            matched = next((hit for hit in hits if quote.strip()
                and " ".join(quote.split()) in " ".join(hit.chunk.text.split())
                and citation_url == _source_url(hit.chunk.metadata)), None)
            if matched is None:
                rejected += 1
                continue
            item = LegalCheckItem(
                category=_s(it.get("category") or it.get("rule_id") or "general"),
                title=_s(it.get("title") or it.get("rule_title") or ""),
                severity=_s(it.get("severity"), "info"),
                status=_s(it.get("status"), "info"),
                description=_s(it.get("description") or ""),
                recommendation=_s(it.get("recommendation") or ""),
                rule_id=_s(it.get("rule_id")) or None,
                rule_title=_s(it.get("rule_title")) or None,
                law_reference=_s(it.get("law_reference") or it.get("article")) or None,
                article=_s(it.get("article") or it.get("law_reference")) or None,
                source=matched.chunk.source,
                quote=quote,
                citation_url=citation_url,
                legal_text_revision=_source_revision(matched.chunk.metadata),
            )
            items.append(item)
        return LegalCheckResult(
            lot_id=lot_id,
            checks=items,
            items=items,
            overall_risk="needs_review" if rejected else _s(data.get("overall_risk"), "needs_review"),
            summary=("Часть правовых выводов не подтверждена источниками. Требуется проверка специалистом."
                     if rejected else _s(data.get("summary"))),
            can_complain_to_counting_committee=False,
            complaint_draft=None,
            corpus_revision=_s(data.get("corpus_revision")) or None,
        )
