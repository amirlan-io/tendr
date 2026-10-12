"""ApplicationGenerator: генерит заявку на участие в госзакупке.

На вход: ID лота + данные поставщика (компания, контакты, цена)
На выход: готовый DOCX пакет документов:
  - Заявка на участие
  - Приложение с техническим предложением
  - Приложение с ценовым предложением
  - Опись документов
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from loguru import logger

from app.core.config import get_settings
from app.schemas.lot import (
    ApplicationRequest,
    ApplicationResult,
    MarginCalculationRequest,
    MarginCalculationResult,
)


def _add_heading(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(13 if level == 1 else 11)


def _add_para(doc: Document, text: str, bold: bool = False) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    if bold:
        run.bold = True
    run.font.size = Pt(11)


def _add_bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph(text, style="List Bullet")
    for r in p.runs:
        r.font.size = Pt(11)


def generate_application_docx(
    request: ApplicationRequest,
    lot_info: dict[str, Any] | None = None,
) -> bytes:
    """Сгенерировать DOCX заявки на участие в госзакупке.

    Args:
        request: данные поставщика (компания, контакты, цена)
        lot_info: информация о лоте (опционально)
    """
    doc = Document()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("ЗАЯВКА НА УЧАСТИЕ В ГОСУДАРСТВЕННЫХ ЗАКУПКАХ")
    run.bold = True
    run.font.size = Pt(14)

    doc.add_paragraph()
    doc.add_paragraph(f"Дата составления: {datetime.now().strftime('%d.%m.%Y г.')}")
    if lot_info and lot_info.get("lot_id"):
        doc.add_paragraph(f"Лот №: {lot_info['lot_id']}")
    if lot_info and lot_info.get("title"):
        doc.add_paragraph(f"Наименование: {lot_info['title']}")
    doc.add_paragraph()

    # === 1. ИНФОРМАЦИЯ О ПОСТАВЩИКЕ ===
    _add_heading(doc, "1. Информация о поставщике", level=1)
    _add_para(doc, f"Наименование: {request.supplier_name}")
    if request.supplier_bin:
        _add_para(doc, f"БИН: {request.supplier_bin}")
    if request.supplier_address:
        _add_para(doc, f"Адрес: {request.supplier_address}")
    if request.supplier_phone:
        _add_para(doc, f"Телефон: {request.supplier_phone}")
    if request.supplier_email:
        _add_para(doc, f"E-mail: {request.supplier_email}")
    if request.supplier_iik or request.supplier_bank:
        _add_para(
            doc,
            f"Банковские реквизиты: {request.supplier_bank or ''} "
            f"{('ИИК ' + request.supplier_iik) if request.supplier_iik else ''}",
        )
    doc.add_paragraph()

    # === 2. ТЕХНИЧЕСКОЕ ПРЕДЛОЖЕНИЕ ===
    _add_heading(doc, "2. Техническое предложение", level=1)
    if request.product_name:
        _add_para(doc, f"Предлагаемый товар: {request.product_name}", bold=True)
    if request.product_description:
        _add_para(doc, request.product_description)
    if request.specs_compliance:
        _add_para(doc, "Соответствие требованиям ТЗ:", bold=True)
        for spec in request.specs_compliance:
            _add_bullet(doc, spec)
    if request.delivery_days:
        _add_para(doc, f"Срок поставки: {request.delivery_days} календарных дней")
    if request.warranty_months:
        _add_para(doc, f"Гарантия: {request.warranty_months} месяцев")
    doc.add_paragraph()

    # === 3. ЦЕНОВОЕ ПРЕДЛОЖЕНИЕ ===
    _add_heading(doc, "3. Ценовое предложение", level=1)
    _add_para(doc, f"Предлагаемая цена: {request.proposed_price_kzt:,.0f} (тенге)", bold=True)
    _add_para(
        doc,
        f"В том числе НДС ({request.vat_rate}%): "
        f"{request.proposed_price_kzt * request.vat_rate / 100:,.0f} тенге",
    )
    if request.proposed_price_kzt > 0 and request.delivery_days and request.delivery_days > 0:
        per_day = request.proposed_price_kzt / request.delivery_days
        _add_para(doc, f"Цена за единицу времени: {per_day:,.0f} тг/день (информационно)")
    if request.price_includes_delivery:
        _add_para(doc, "Цена включает доставку.")
    else:
        _add_para(doc, "Доставка оплачивается отдельно.")
    _add_para(
        doc,
        f"Условия оплаты: {request.payment_terms or 'в соответствии с законодательством РК'}",
    )
    doc.add_paragraph()

    # === 4. СООТВЕТСТВИЕ КВАЛИФИКАЦИОННЫМ ТРЕБОВАНИЯМ ===
    _add_heading(doc, "4. Квалификационные требования", level=1)
    if request.qualifications:
        for qual in request.qualifications:
            _add_bullet(doc, qual)
    else:
        _add_para(doc, "Подтверждаем соответствие квалификационным требованиям ТЗ.")
    doc.add_paragraph()

    # === 5. ПРИЛАГАЕМЫЕ ДОКУМЕНТЫ ===
    _add_heading(doc, "5. Перечень прилагаемых документов", level=1)
    if request.documents:
        for i, d in enumerate(request.documents, 1):
            _add_para(doc, f"{i}. {d}")
    else:
        default_docs = [
            "Копия устава (для юр. лиц)",
            "Справка об отсутствии налоговой задолженности",
            "Сведения о квалификации (опыт, сертификаты)",
            "Технические характеристики предлагаемого товара",
        ]
        for i, d in enumerate(default_docs, 1):
            _add_para(doc, f"{i}. {d}")
    doc.add_paragraph()

    # === Подвал ===
    _add_para(doc, "")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run(f"Директор {request.supplier_name}")
    run.font.size = Pt(11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run("____________________ / ФИО /")
    run.font.size = Pt(11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run(f"«__» __________ {datetime.now().year} г.")
    run.font.size = Pt(11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run("М.П. (при наличии)")
    run.font.size = Pt(10)
    run.italic = True

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ───── Калькулятор цены ─────


def calculate_margin(req: MarginCalculationRequest) -> MarginCalculationResult:
    """Рассчитать оптимальную цену для участия в лоте.

    Args:
        req: себестоимость, налоги, желаемая маржа, цена конкурента

    Returns:
        минимальная цена (чтобы не уйти в минус)
        оптимальная цена (с желаемой маржой)
        агрессивная цена (на 3-5% ниже конкурента)
        прогноз прибыли
    """
    base = req.unit_cost_kzt  # себестоимость единицы
    vat = req.vat_rate / 100.0
    logistics = req.logistics_per_unit_kzt
    overhead = req.overhead_per_unit_kzt  # накладные расходы

    # Минимальная цена (безубыточность)
    cost_total = base + logistics + overhead
    min_price = cost_total * (1 + vat)

    # Оптимальная цена. Маржа — доля прибыли в выручке без НДС,
    # поэтому используется деление на (1 - margin), а не наценка cost * (1 + margin).
    target_margin = req.desired_margin_pct / 100.0
    if target_margin > 0:
        optimal_net_price = cost_total / (1 - target_margin)
        optimal_price = optimal_net_price * (1 + vat)
    else:
        optimal_net_price = cost_total
        optimal_price = min_price

    # Агрессивная цена (на 5% ниже конкурента, но не ниже min+10%)
    if req.competitor_price_kzt and req.competitor_price_kzt > 0:
        aggressive_price = req.competitor_price_kzt * 0.95
        # Никогда не ниже точки безубыточности.
        aggressive_price = max(aggressive_price, min_price)
        # Не выше optimal_price
        aggressive_price = min(aggressive_price, optimal_price)
    else:
        aggressive_price = max(optimal_price * 0.95, min_price)

    # Рекомендация
    if req.competitor_price_kzt and req.competitor_price_kzt > 0:
        if req.competitor_price_kzt < cost_total * 1.1:
            recommendation = (
                f"⚠ ВНИМАНИЕ: Цена конкурента ({req.competitor_price_kzt:,.0f} ₸) "
                f"ниже вашей себестоимости. Участие может быть убыточным!"
            )
        elif req.competitor_price_kzt < optimal_price * 0.9:
            recommendation = (
                f"Конкурент демпингует. Рекомендуем не опускаться ниже "
                f"{aggressive_price:,.0f} ₸ — иначе маржа будет меньше {req.desired_margin_pct}%."
            )
        else:
            recommendation = (
                f"Публичный ценовой ориентир: {req.competitor_price_kzt:,.0f} ₸. "
                f"Расчётная цена с целевой маржой {req.desired_margin_pct}%: "
                f"{optimal_price:,.0f} ₸. Победа не гарантируется."
            )
    else:
        recommendation = (
            f"Нет данных о ценах конкурентов. Рекомендуемая цена: {optimal_price:,.0f} ₸ "
            f"(целевая маржа {req.desired_margin_pct}% от выручки без НДС)."
        )

    # НДС не является прибылью: из цены с НДС сначала выделяем чистую выручку.
    profit_optimal = optimal_price / (1 + vat) - cost_total
    profit_aggressive = aggressive_price / (1 + vat) - cost_total

    return MarginCalculationResult(
        min_price=min_price,
        optimal_price=optimal_price,
        aggressive_price=aggressive_price,
        profit_at_optimal=profit_optimal,
        profit_at_aggressive=profit_aggressive,
        margin_at_optimal_pct=req.desired_margin_pct,
        recommendation=recommendation,
    )
