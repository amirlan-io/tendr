"""Documenter Agent: анализ ТЗ → чек-лист требований + пакет документов."""

from __future__ import annotations

from app.agents.base import Agent
from app.schemas.lot import (
    LotAnalysis,
    ProcurementMethod,
    RequirementItem,
)


def _s(value, default: str = "") -> str:
    """Защита от None: LLM иногда возвращает null вместо строки."""
    if value is None:
        return default
    return str(value)


class DocumenterAgent(Agent):
    name = "documenter"

    system_prompt = (
        "Ты — AI-ассистент для малого и среднего бизнеса Казахстана, "
        "помогающий готовить заявки на государственные закупки по "
        "Закону Республики Казахстан «О государственных закупках».\n\n"
        "Твоя задача: проанализировать техническое задание лота и вернуть "
        "СТРОГО валидный JSON со следующей структурой:\n"
        "{\n"
        '  "title": "краткое название лота (макс 100 символов)",\n'
        '  "customer": "название заказчика или null",\n'
        '  "method": "tender|auction|request_quotes|single_source|other",\n'
        '  "deadline": "ISO datetime или null",\n'
        '  "budget_kzt": число или null,\n'
        '  "summary": "краткое резюме лота в 1-2 предложениях (макс 200 символов)",\n'
        '  "requirements": [\n'
        '    {"code": "snake_code", "title": "Заголовок (коротко)", '
        '"description": "Кратко (1 предложение, до 50 слов)", '
        '"is_mandatory": true/false, "source_quote": "краткая цитата до 60 символов"}\n'
        "  ],\n"
        '  "documents_required": ["перечень документов, не более 3-5 штук"],\n'
        '  "red_flags": ["список подозрительных пунктов, не более 3 штук"]\n'
        "}\n\n"
        "Правила:\n"
        "1. Выделяй только реальные требования, не выдумывай. ВАЖНО: если в ТехЗадании нет конкретного требования — НЕ придумывай его, а ставь пустой массив.\n"
        "2. В source_quote — КРАТКАЯ цитата (макс 60 символов).\n"
        "3. В red_flags — только реальные нарушения Закона РК «О госзакупках». Если нарушений нет — пустой массив.\n"
        "4. Если данных не хватает — ставь null или пустой массив. Лучше вернуть пустой ответ, чем выдумывать.\n"
        "5. МАКСИМУМ 3 требования, 3 red_flags, 3 документа — пиши кратко!\n"
        "6. description в требованиях — максимум 1 предложение.\n"
        "7. Ответ — ТОЛЬКО JSON, без markdown, без пояснений."
    )

    async def run(self, lot_text: str, *, lot_id: str) -> LotAnalysis:
        # Ограничиваем длину промпта — 12К символов (≈ 3-4К токенов),
        # чтобы влезло в контекстное окно Mistral Large с запасом на ответ.
        # Если текст длиннее — берём начало + конец (там обычно ключевая информация).
        if len(lot_text) > 12000:
            half = 6000
            lot_text = (
                lot_text[:half] + "\n\n... [середина документа опущена] ...\n\n" + lot_text[-half:]
            )

        prompt = (
            f"ID лота: {lot_id}\n\n"
            f"Техническое задание лота:\n```\n{lot_text}\n```\n\n"
            "Проанализируй и верни JSON строго по описанной структуре."
        )
        data = await self._chat_json(prompt)
        if not data:
            return LotAnalysis(
                lot_id=lot_id,
                title="(не удалось проанализировать)",
                customer="(неизвестно)",
                method=ProcurementMethod.OTHER,
                summary="",
            )

        try:
            method_str = (data.get("method") or "other").lower()
            method = ProcurementMethod(method_str)
        except (ValueError, AttributeError):
            method = ProcurementMethod.OTHER

        requirements = [
            RequirementItem(
                # Поддерживаем оба варианта полей от LLM
                name=_s(r.get("name") or r.get("title") or r.get("code")),
                value=_s(r.get("value") or r.get("description") or ""),
                is_critical=bool(
                    r.get("is_critical")
                    if "is_critical" in r
                    else r.get("is_mandatory", True)
                ),
                category=_s(r.get("category") or ""),
            )
            for r in data.get("requirements", [])
        ]

        return LotAnalysis(
            lot_id=lot_id,
            title=_s(data.get("title"), "(без названия)"),
            customer=_s(data.get("customer"), "(не указан)"),
            method=method,
            deadline=data.get("deadline"),
            budget_kzt=data.get("budget_kzt"),
            requirements=requirements,
            documents_required=[_s(d) for d in data.get("documents_required", []) if d is not None],
            summary=_s(data.get("summary")),
            red_flags=[_s(f) for f in data.get("red_flags", []) if f is not None],
        )
