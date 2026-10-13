"""Оркестратор: связывает парсер лота, агентов и freemium-квоты.

Точка входа: analyze_lot(input).
"""

from __future__ import annotations

import re
from datetime import datetime

from loguru import logger

from app.agents.documenter import DocumenterAgent
from app.agents.base import AnalysisUnavailable
from app.agents.legal import LegalAgent
from app.schemas.lot import (
    CustomerScore,
    LegalCheckResult,
    LotAnalysis,
    LotAnalysisResponse,
    LotCreate,
    MarginEstimate,
    ProcurementMethod,
    RequirementItem,
    SourceDocument,
)
from app.services.document_reader import extract_text
from app.services.goszakup_parser import (
    LotNotFoundError,
    ParsedLot,
    build_lot_url,
    get_parser,
)
from app.services.official_documents import fetch_official_documents
from app.services.scoring import (
    estimate_margin_pct,
    get_customer_score,
)


class QuotaExceeded(Exception):
    """Пользователь исчерпал лимит freemium."""


def _normalized_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("×", "x").replace("х", "x")).strip().casefold()


def _requirement_has_evidence(requirement: RequirementItem, source_text: str) -> bool:
    """Подтвердить, что цитата требования действительно есть в источнике."""

    quote = _normalized_evidence(requirement.source_quote)
    source = _normalized_evidence(source_text)
    return len(quote) >= 8 and quote in source


def _claim_has_evidence(claim: str, source_text: str) -> bool:
    normalized = _normalized_evidence(claim)
    return len(normalized) >= 5 and normalized in _normalized_evidence(source_text)


class LotOrchestrator:
    def __init__(self, session=None) -> None:
        self._parser = get_parser()
        self._documenter = DocumenterAgent()
        self._legal = LegalAgent()
        self._session = session  # для скоринга заказчика

    async def analyze_lot(
        self,
        lot_input: LotCreate,
        *,
        user_id: int,
        is_pilot: bool,
        used_this_month: int,
        free_limit: int,
        with_legal: bool = True,
    ) -> LotAnalysisResponse:
        """Полный цикл: получить ТЗ → проанализировать → (опционально) проверить юридически."""
        # Freemium-проверка
        limit = 999 if is_pilot else free_limit
        if used_this_month > limit:
            raise QuotaExceeded(
                f"Лимит бесплатных заявок на месяц исчерпан ({used_this_month}/{limit})."
            )

        # 1. Получаем текст ТЗ
        try:
            parsed = await self._resolve_lot(lot_input)
        except LotNotFoundError as e:
            logger.info("Lot not found: {}", e.lot_id)
            stub_lot = LotAnalysis(
                lot_id=e.lot_id,
                title=f"Лот {e.lot_id}",
                customer="(лот не найден)",
                method=ProcurementMethod.OTHER,
                source_url=build_lot_url(lot_input.source_url or e.lot_id),
                summary="",
                red_flags=[],
                requirements=[],
                documents_required=[],
            )
            return LotAnalysisResponse(
                lot=stub_lot,
                legal=None,
                created_at=datetime.utcnow(),
                incomplete=True,
                incomplete_reason=(
                    f"Лот с ID *{e.lot_id}* не найден на goszakup.gov.kz.\n\n"
                    "**Возможные причины:**\n"
                    "• Использован внутренний номер заказчика (например, `87083002-OIZ`) — "
                    "на goszakup он не существует. Нужен **ID объявления** (число из ссылки на лот).\n"
                    "• Лот ещё не опубликован или уже завершён/отменён.\n"
                    "• Опечатка в номере.\n\n"
                    "**Что делать:**\n"
                    "1. Откройте https://goszakup.gov.kz\n"
                    "2. Найдите лот в поиске\n"
                    "3. Скопируйте **числовой ID из URL** (например, `17266377`)\n"
                    "4. Вставьте его сюда (без дефиса и суффикса)\n\n"
                    "Или пришлите PDF/DOCX с ТЗ — проанализируем без токена."
                ),
            )

        # Официальная карточка содержит лишь краткое описание. Полное ТЗ у
        # Госзакупок хранится в Lots.Files; скачиваем и читаем только файлы с
        # официального allowlist-домена. Именно этот текст затем получает ИИ.
        official_files = list((parsed.extra or {}).get("source_documents") or [])
        extracted_documents = await fetch_official_documents(official_files)
        source_documents = [
            SourceDocument(
                name=document.name,
                document_type=document.document_type,
                url=document.url,
                extracted=document.extracted,
                text_chars=len(document.text),
                error=document.error,
            )
            for document in extracted_documents
        ]
        official_card_text = (parsed.technical_specification or "").strip()
        source_sections = []
        if official_card_text:
            source_sections.append(
                "=== ИСТОЧНИК: Официальная карточка лота ===\n" + official_card_text
            )
        source_sections.extend(
            "=== ИСТОЧНИК: "
            f"{document.document_type} — {document.name} ===\n{document.text}"
            for document in extracted_documents
            if document.extracted
        )
        if source_sections:
            parsed.technical_specification = "\n\n".join(source_sections)

        # 1.5 Guard: если парсер вернул почти пусто — не вызываем LLM на пустых данных,
        # а просим пользователя прислать текст/PDF.
        # НО: если в тексте есть хоть какие-то реальные данные (ТЗ из PDF/приложение)
        # — пропускаем Documenter, Legal сработает на том что есть.
        ts = (parsed.technical_specification or "").strip()
        desc = (parsed.description or "").strip()
        # Документ «богатый» если:
        # - Много текста в ТЗ (>=300 символов) — обычно это PDF-приложение
        # - Vision нашёл картинки (ОПИСАНИЯ КАРТИНОК)
        # - Есть размеры или другие тех. характеристики
        is_rich_doc = (
            len(ts) >= 300
            or "ОПИСАНИЯ КАРТИНОК" in ts
            or "мм" in ts.lower()
            and any(c.isdigit() for c in ts)  # размеры с цифрами
        )
        is_completely_empty = not parsed.customer_name and len(ts) < 100 and len(desc) < 100
        if is_completely_empty and not is_rich_doc:
            is_incomplete = True
        else:
            is_incomplete = False  # Пропускаем — есть данные для анализа
        if is_incomplete:
            logger.warning(
                "Incomplete lot data for id={} (ts_len={}, desc_len={})",
                parsed.lot_id,
                len(ts),
                len(desc),
            )
            stub_lot = LotAnalysis(
                lot_id=parsed.lot_id,
                title=parsed.title or f"Лот {parsed.lot_id}",
                customer=parsed.customer_name or "(не удалось извлечь)",
                method=parsed.method,
                source_url=self._resolve_source_url(parsed, lot_input),
                summary="",
                red_flags=[],
                requirements=[],
                documents_required=[],
            )
            return LotAnalysisResponse(
                lot=stub_lot,
                legal=None,
                created_at=datetime.utcnow(),
                incomplete=True,
                incomplete_reason=(
                    "Не удалось получить данные лота с goszakup.gov.kz "
                    "(API-токен отсутствует, HTML-каркас без данных). "
                    "Пришлите, пожалуйста, текст технического задания "
                    "или PDF-файл с лотом — и я проанализирую его сразу."
                ),
            )

        # 2. Анализ Documenter-агентом
        text_for_agent = (
            f"Название: {parsed.title}\n"
            f"Заказчик: {parsed.customer_name} (БИН {parsed.customer_bin or '—'})\n"
            f"Способ: {parsed.method}\n"
            f"Бюджет: {parsed.budget_kzt} тг\n"
            f"Срок подачи заявок: {parsed.deadline or '—'}\n"
            f"Описание: {parsed.description}\n\n"
            f"Техническое задание:\n{parsed.technical_specification}"
        )
        analysis = await self._documenter.run(text_for_agent, lot_id=parsed.lot_id)
        logger.info("Documenter agent done for lot {}", parsed.lot_id)

        # Даже при временной недоступности обеих LLM не выбрасываем уже
        # полученные официальные данные. Показываем дословный фрагмент ТЗ и
        # помечаем его как требующий ручной проверки, не выдумывая требований.
        documenter_failed = analysis.title in {
            "",
            "(не удалось проанализировать)",
            "(без названия)",
        }
        if documenter_failed:
            if lot_input.raw_text:
                raise AnalysisUnavailable("Не удалось выполнить ИИ-анализ загруженного документа.")
            analysis.title = parsed.title or f"Лот {parsed.lot_id}"
            analysis.customer = parsed.customer_name or "(не указан)"
            analysis.procurement_method = parsed.method or ProcurementMethod.OTHER
            analysis.summary = (parsed.description or ts)[:800]
            analysis.technical_specification = ts
            analysis.documents_required = list(parsed.documents_required or [])[:10]
            if parsed.requirements:
                analysis.requirements = [
                    RequirementItem(
                        name=f"Требование {index}",
                        value=str(value)[:1200],
                        is_critical=True,
                        category="техническое",
                    )
                    for index, value in enumerate(parsed.requirements[:10], start=1)
                    if str(value).strip()
                ]
            elif ts:
                analysis.requirements = [
                    RequirementItem(
                        name="Техническая спецификация",
                        value=ts[:1200],
                        is_critical=True,
                        category="техническое",
                    )
                ]
            analysis.warnings.append(
                "Структурированный ИИ-разбор временно недоступен: показаны исходные данные официального лота."
            )

        # Не показываем утверждение как факт, если агент не приложил дословную
        # цитату, которую можно найти в официальной карточке или приложении.
        if not documenter_failed:
            proposed_requirements = list(analysis.requirements)
            analysis.requirements = [
                requirement
                for requirement in proposed_requirements
                if _requirement_has_evidence(requirement, parsed.technical_specification)
            ]
            rejected_count = len(proposed_requirements) - len(analysis.requirements)
            if rejected_count:
                analysis.warnings.append(
                    f"Не показано неподтверждённых требований: {rejected_count}."
                )
            proposed_documents = list(analysis.documents_required)
            analysis.documents_required = [
                document
                for document in proposed_documents
                if _claim_has_evidence(document, parsed.technical_specification)
            ]
            proposed_red_flags = list(analysis.red_flags)
            analysis.red_flags = [
                flag
                for flag in proposed_red_flags
                if _claim_has_evidence(flag, parsed.technical_specification)
            ]
            unverified_claims = (
                len(proposed_documents)
                - len(analysis.documents_required)
                + len(proposed_red_flags)
                - len(analysis.red_flags)
            )
            if unverified_claims:
                analysis.warnings.append(
                    f"Не показано неподтверждённых документов или рисков: {unverified_claims}."
                )

        # 2.1 Дополняем LotAnalysis реальными данными из парсера (Documenter
        # часто не извлекает budget/deadline из текста, но они у нас уже есть).
        if parsed.budget_kzt is not None and not analysis.amount_kzt:
            analysis.amount_kzt = parsed.budget_kzt
        if parsed.deadline and not analysis.deadline:
            analysis.deadline = str(parsed.deadline)
        if parsed.customer_name and (not analysis.customer or analysis.customer in {"(не указан)", "(неизвестно)", ""}):
            analysis.customer = parsed.customer_name
        if parsed.method and (not analysis.procurement_method or analysis.procurement_method == "other"):
            analysis.procurement_method = parsed.method
        analysis.technical_specification = parsed.technical_specification
        analysis.source_documents = source_documents
        analysis.source_url = self._resolve_source_url(parsed, lot_input)

        # 3. Юридическая проверка
        legal: LegalCheckResult | None = None
        if with_legal:
            legal = await self._legal.run(text_for_agent, lot_id=parsed.lot_id)
            logger.info("Legal agent done for lot {} risk={}", parsed.lot_id, legal.overall_risk)

        # 4. Скоринг заказчика + оценка маржинальности
        customer_score_data: CustomerScore | None = None
        if self._session is not None and parsed.customer_name:
            try:
                score_dict = await get_customer_score(self._session, parsed.customer_name)
                customer_score_data = CustomerScore(**score_dict)
            except Exception as e:  # noqa: BLE001
                logger.warning("Customer score failed: {}", e)

        margin_data = estimate_margin_pct(parsed.title, parsed.description)
        margin_est = MarginEstimate(**margin_data)

        # 5. Рекомендация: участвовать / review / skip
        recommendation = self._make_recommendation(
            risk=legal.overall_risk if legal else "needs_review",
            trust=customer_score_data.trust_score if customer_score_data else 50.0,
            margin_pct=margin_est.estimated_margin_pct,
        )

        analysis.customer_score = customer_score_data
        analysis.margin_estimate = margin_est
        analysis.recommendation = recommendation

        failed_official_documents = [document for document in source_documents if not document.extracted]
        incomplete_reasons: list[str] = []
        if documenter_failed:
            incomplete_reasons.append("структурированный разбор временно недоступен")
        if (parsed.extra or {}).get("source_documents_lookup_failed"):
            incomplete_reasons.append(
                "не удалось проверить список официальных вложений лота"
            )
        if len(official_files) > len(extracted_documents):
            incomplete_reasons.append("часть официальных вложений не обработана из-за лимита")
        if failed_official_documents:
            incomplete_reasons.append(
                "не удалось прочитать: "
                + ", ".join(document.name for document in failed_official_documents[:3])
            )
        if extracted_documents and not analysis.requirements:
            incomplete_reasons.append(
                "в официальном ТЗ не удалось подтвердить структурированные требования"
            )

        return LotAnalysisResponse(
            lot=analysis,
            legal=legal,
            created_at=datetime.utcnow(),
            incomplete=bool(incomplete_reasons),
            incomplete_reason="; ".join(incomplete_reasons),
        )

    @staticmethod
    def _resolve_source_url(parsed: ParsedLot, lot_input: LotCreate) -> str | None:
        """Ссылка на исходное объявление: сначала парсер, затем входной URL/ID.

        Приоритет у extra парсера: он знает URL фактического редиректа,
        а не то, что пользователь вставил.
        """
        parsed_url = (parsed.extra or {}).get("source_url")
        if parsed_url:
            return str(parsed_url)
        return build_lot_url(lot_input.source_url or lot_input.source_id or parsed.lot_id)

    @staticmethod
    def _make_recommendation(*, risk: str, trust: float, margin_pct: float) -> str:
        """Эвристика: участвовать / review / skip."""
        # Неизвестный/неполный юридический результат нельзя превращать в
        # зелёную рекомендацию только из-за хорошей оценочной маржи.
        if risk not in {"low", "medium", "high"}:
            return "review"
        if risk == "high" and trust < 40:
            return "skip"
        if risk == "high" or trust < 30:
            return "review"
        if margin_pct < 10:
            return "review"  # низкая маржа — стоит подумать
        if trust >= 60 and margin_pct >= 18:
            return "participate"
        return "review"

    async def _resolve_lot(self, lot_input: LotCreate) -> ParsedLot:
        """Привести входные данные к ParsedLot."""
        # LotCreate.method — это str | None, не Enum, поэтому .value не нужен.
        method_value = lot_input.method or "tender"
        if lot_input.raw_text:
            return ParsedLot(
                lot_id=lot_input.source_id or "raw",
                title="(введено вручную)",
                customer_name=lot_input.customer_name or "—",
                customer_bin=lot_input.customer_bin,
                method=method_value,
                deadline=None,
                budget_kzt=None,
                description="",
                technical_specification=lot_input.raw_text,
            )
        if lot_input.source_url or lot_input.source_id:
            value = lot_input.source_url or lot_input.source_id or ""
            return await self._parser.fetch_lot(value)
        if lot_input.customer_name and lot_input.method:
            # мало данных — попросим уточнить
            return ParsedLot(
                lot_id="manual",
                title=lot_input.customer_name,
                customer_name=lot_input.customer_name,
                customer_bin=lot_input.customer_bin,
                method=method_value,
                deadline=None,
                budget_kzt=None,
                description="",
                technical_specification="(ТЗ не предоставлено)",
            )
        raise ValueError("Нужно передать source_url / source_id / raw_text.")


# helper для случая, когда ТЗ пришло файлом
async def analyze_uploaded_file(
    file_path: str,
    *,
    user_id: int,
    is_pilot: bool,
    used_this_month: int,
    free_limit: int,
    session=None,
) -> LotAnalysisResponse:
    from uuid import uuid4

    text = await extract_text(file_path)
    orchestrator = LotOrchestrator(session=session)
    return await orchestrator.analyze_lot(
        LotCreate(raw_text=text, source_id=f"uploaded-{uuid4().hex}"),
        user_id=user_id,
        is_pilot=is_pilot,
        used_this_month=used_this_month,
        free_limit=free_limit,
    )
