"""Генерация DOCX-документов: жалобы, заявки, отчёты.

Используется для:
- complaint_draft (жалоба в Счётный комитет)
- application_package (пакет документов на участие в лоте)
- full_report (общий отчёт по лоту для пользователя)
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


def _add_heading(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(14 if level == 1 else 12)


def _add_para(doc: Document, text: str, bold: bool = False) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    if bold:
        run.bold = True
    run.font.size = Pt(11)


def _add_bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph(text, style="List Bullet")
    for run in p.runs:
        run.font.size = Pt(11)

def generate_tz_pdf(
    tz: dict[str, Any],
    *,
    organization: str | None = None,
    organization_bin: str | None = None,
) -> bytes:
    """Сгенерировать PDF с техническим заданием для госзакупки (B2G)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.colors import HexColor, gray
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=tz.get("title", "Техническое задание"),
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Title"],
        fontSize=16, textColor=HexColor("#0E7C7B"),
        alignment=TA_CENTER, spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"],
        fontSize=11, alignment=TA_CENTER, textColor=gray, spaceAfter=4,
    )
    h1_style = ParagraphStyle(
        "H1", parent=styles["Heading1"],
        fontSize=13, textColor=HexColor("#0E7C7B"),
        spaceBefore=12, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, leading=13, spaceAfter=4,
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=body_style, leftIndent=14, bulletIndent=4,
    )
    note_style = ParagraphStyle(
        "Note", parent=body_style, fontSize=9, textColor=gray, alignment=TA_CENTER,
    )
    flag_style = ParagraphStyle(
        "Flag", parent=body_style, leftIndent=10, spaceAfter=3,
    )

    story = []

    # Шапка
    story.append(Paragraph("ТЕХНИЧЕСКОЕ ЗАДАНИЕ", title_style))
    if organization:
        story.append(Paragraph(f"<b>{organization}</b>", subtitle_style))
    if organization_bin:
        story.append(Paragraph(f"БИН: {organization_bin}", subtitle_style))
    story.append(Paragraph(
        f"Дата составления: {datetime.now().strftime('%d.%m.%Y')}", subtitle_style,
    ))
    story.append(Spacer(1, 10))

    def heading(text):
        story.append(Paragraph(text, h1_style))

    def para(text):
        if text:
            for line in str(text).split("\n"):
                if line.strip():
                    story.append(Paragraph(line.strip(), body_style))

    def bullets(items):
        for it in items or []:
            story.append(Paragraph(f"• {it}", bullet_style))

    # 1. Название
    heading("1. Наименование закупки")
    para(tz.get("title", "—"))
    if tz.get("category"):
        para(f"Категория: {tz['category']}")
    if tz.get("procurement_method"):
        method_label = {
            "tender": "Открытый конкурс",
            "auction": "Электронный аукцион",
            "request_quotes": "Запрос ценовых предложений",
            "single_source": "Из одного источника",
            "other": "Иной способ",
        }.get(tz["procurement_method"], tz["procurement_method"])
        para(f"Способ закупки: {method_label}")

    # 2. Описание
    if tz.get("description"):
        heading("2. Описание и обоснование")
        para(tz["description"])

    # 3. Тех. спецификация
    heading("3. Техническая спецификация")
    spec = tz.get("technical_specification", "—")
    if isinstance(spec, dict):
        for key, val in spec.items():
            para(f"<b>{key}:</b> {val}")
    else:
        para(spec)

    # 4. Бюджет
    if tz.get("estimated_budget_kzt"):
        heading("4. Бюджет")
        para(f"Предполагаемая сумма: {tz['estimated_budget_kzt']:,.0f} тенге")

    # 5. Сроки
    heading("5. Сроки и условия поставки")
    if tz.get("deadline"):
        para(f"Срок подачи заявок до: {tz['deadline']}")
    if tz.get("delivery_days"):
        para(f"Срок поставки: {tz['delivery_days']} календарных дней")
    if tz.get("delivery_address"):
        para(f"Адрес поставки: {tz['delivery_address']}")

    # 6. Квалификации
    quals = tz.get("qualification_requirements") or []
    if quals:
        heading("6. Квалификационные требования к поставщику")
        bullets(quals)

    # 7. Документы
    req_docs = tz.get("documents_required") or []
    if req_docs:
        heading("7. Перечень документов")
        bullets(req_docs)

    # 8. Критерии
    if tz.get("evaluation_criteria"):
        heading("8. Критерии оценки заявок")
        crit = tz["evaluation_criteria"]
        if isinstance(crit, dict):
            for k, v in crit.items():
                para(f"<b>{k}:</b> {v}")
        else:
            para(str(crit))

    # 9. Red flags
    flags = tz.get("red_flags") or []
    if flags:
        heading("9. Замечания (проверьте)")
        for f in flags:
            story.append(Paragraph(
                f'<font color="#dc2626">⚠</font> {f}', flag_style,
            ))

    # 10. Warnings
    warnings = tz.get("warnings") or []
    if warnings:
        heading("10. Рекомендации")
        for w in warnings:
            story.append(Paragraph(
                f'<font color="#d97706">!</font> {w}', flag_style,
            ))

    # 11. Compliance
    if tz.get("legal_compliance"):
        heading("11. Соответствие законодательству")
        comp = tz["legal_compliance"]
        comp_label = {
            "ok": "✓ Соответствует",
            "review": "⚠ Требует проверки",
            "violation": "✗ Есть нарушения",
        }.get(comp, comp)
        color = {"ok": "#059669", "review": "#d97706", "violation": "#dc2626"}.get(comp, "#000")
        story.append(Paragraph(
            f'<font color="{color}"><b>{comp_label}</b></font>', body_style,
        ))
        if tz.get("compliance_notes"):
            para(tz["compliance_notes"])

    # Подвал
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "Сформировано автоматически системой Tendr (AI-ассистент для МСБ РК)",
        note_style,
    ))

    doc.build(story)
    return buf.getvalue()



def generate_complaint_docx(
    lot_id: str,
    complaint_draft: dict[str, str] | str,
    lot_title: str = "",
) -> bytes:
    """Сгенерировать DOCX жалобы в Счётный комитет."""
    doc = Document()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("ЖАЛОБА")
    run.bold = True
    run.font.size = Pt(16)

    doc.add_paragraph(
        f"в Счётный комитет по контролю за осуществлением государственных закупок "
        f"Республики Казахстан"
    ).alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"Дата: {datetime.now().strftime('%d.%m.%Y')}")
    doc.add_paragraph(f"Лот №: {lot_id}")
    if lot_title:
        doc.add_paragraph(f"Предмет закупки: {lot_title}")

    doc.add_paragraph()

    if isinstance(complaint_draft, dict):
        for key, label in [
            ("шапка", "От кого"),
            ("обстоятельства", "Обстоятельства дела"),
            ("нарушенные_нормы", "Нарушенные нормы"),
            ("просьба", "Просительная часть"),
        ]:
            text = complaint_draft.get(key)
            if not text:
                continue
            _add_heading(doc, label, level=2)
            _add_para(doc, text)
            doc.add_paragraph()
    else:
        _add_para(doc, str(complaint_draft))

    doc.add_paragraph()
    doc.add_paragraph("___________________ / ФИО /")
    doc.add_paragraph("Подпись")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_report_docx(lot: dict[str, Any], legal: dict[str, Any] | None) -> bytes:
    """Сгенерировать DOCX-отчёт по лоту."""
    doc = Document()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("ОТЧЁТ ПО ЛОТУ")
    run.bold = True
    run.font.size = Pt(16)

    doc.add_paragraph(f"Лот №: {lot.get('lot_id', '—')}")
    doc.add_paragraph(f"Сформирован: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    doc.add_paragraph()

    _add_heading(doc, "Общая информация", level=1)
    _add_para(doc, f"Название: {lot.get('title', '—')}", bold=True)
    _add_para(doc, f"Заказчик: {lot.get('customer', '—')}")
    _add_para(doc, f"Способ закупки: {lot.get('method', '—')}")
    if lot.get("budget_kzt"):
        _add_para(doc, f"Бюджет: {lot['budget_kzt']:,.0f} ₸")
    if lot.get("deadline"):
        _add_para(doc, f"Срок подачи: {lot['deadline']}")

    if lot.get("summary"):
        _add_heading(doc, "Краткое описание", level=1)
        _add_para(doc, lot["summary"])

    reqs = lot.get("requirements") or []
    if reqs:
        _add_heading(doc, f"Требования ({len(reqs)})", level=1)
        for r in reqs:
            if not isinstance(r, dict):
                continue
            label = r.get("title") or r.get("description") or "—"
            _add_bullet(doc, label)

    flags = lot.get("red_flags") or []
    if flags:
        _add_heading(doc, f"Красные флаги ({len(flags)})", level=1)
        for f in flags:
            _add_bullet(doc, str(f))

    docs = lot.get("documents_required") or []
    if docs:
        _add_heading(doc, f"Необходимые документы ({len(docs)})", level=1)
        for d in docs:
            _add_bullet(doc, str(d))

    if legal:
        items = legal.get("items") or []
        if items:
            _add_heading(doc, f"Юридические нарушения ({len(items)})", level=1)
            for it in items:
                if not isinstance(it, dict):
                    continue
                ref = it.get("law_reference") or it.get("rule_id") or "—"
                desc = it.get("description") or it.get("rule_title") or ""
                _add_bullet(doc, f"{ref}: {desc}")

        draft = legal.get("complaint_draft")
        if draft:
            _add_heading(doc, "Черновик жалобы в Счётный комитет", level=1)
            if isinstance(draft, dict):
                for k in ("шапка", "обстоятельства", "нарушенные_нормы", "просьба"):
                    if draft.get(k):
                        _add_heading(doc, k, level=2)
                        _add_para(doc, draft[k])
                        doc.add_paragraph()
            elif isinstance(draft, str):
                _add_para(doc, draft)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_tz_docx(
    tz: dict[str, Any],
    *,
    organization: str | None = None,
    organization_bin: str | None = None,
) -> bytes:
    """Сгенерировать DOCX с техническим заданием для госзакупки (B2G).

    Args:
        tz: результат B2G-агента (B2GResult как dict)
        organization: название организации-заказчика
        organization_bin: БИН заказчика
    """
    doc = Document()

    # Шапка с реквизитами заказчика
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("ТЕХНИЧЕСКОЕ ЗАДАНИЕ")
    run.bold = True
    run.font.size = Pt(18)

    if organization:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(organization)
        r.bold = True
        r.font.size = Pt(12)
    if organization_bin:
        doc.add_paragraph(f"БИН: {organization_bin}").alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"Дата составления: {datetime.now().strftime('%d.%m.%Y %г.')}")
    doc.add_paragraph()

    # 1. Название и предмет
    _add_heading(doc, "1. Наименование закупки", level=1)
    _add_para(doc, tz.get("title", "—"), bold=True)
    if tz.get("category"):
        _add_para(doc, f"Категория: {tz['category']}")
    if tz.get("procurement_method"):
        method_label = {
            "tender": "Открытый конкурс",
            "auction": "Электронный аукцион",
            "request_quotes": "Запрос ценовых предложений",
            "single_source": "Из одного источника",
            "other": "Иной способ",
        }.get(tz["procurement_method"], tz["procurement_method"])
        _add_para(doc, f"Способ закупки: {method_label}")

    # 2. Описание
    if tz.get("description"):
        _add_heading(doc, "2. Описание и обоснование", level=1)
        for para in tz["description"].split("\n"):
            if para.strip():
                _add_para(doc, para.strip())

    # 3. Техническая спецификация
    _add_heading(doc, "3. Техническая спецификация", level=1)
    spec = tz.get("technical_specification", "—")

    # Если spec — это dict (от LLM), выводим структурированно
    if isinstance(spec, dict):
        for key, val in spec.items():
            p = doc.add_paragraph()
            r = p.add_run(f"{key}: ")
            r.bold = True
            p.add_run(str(val))
    else:
        # Если строка — разбиваем по переводам строк или точкам
        for line in str(spec).split("\n"):
            if line.strip():
                _add_para(doc, line.strip())

    # 4. Бюджет
    if tz.get("estimated_budget_kzt"):
        _add_heading(doc, "4. Бюджет", level=1)
        _add_para(doc, f"Предполагаемая сумма: {tz['estimated_budget_kzt']:,.0f} тенге")

    # 5. Сроки и адрес
    _add_heading(doc, "5. Сроки и условия поставки", level=1)
    if tz.get("deadline"):
        _add_para(doc, f"Срок подачи заявок до: {tz['deadline']}")
    if tz.get("delivery_days"):
        _add_para(doc, f"Срок поставки: {tz['delivery_days']} календарных дней")
    if tz.get("delivery_address"):
        _add_para(doc, f"Адрес поставки: {tz['delivery_address']}")

    # 6. Квалификационные требования
    quals = tz.get("qualification_requirements") or []
    if quals:
        _add_heading(doc, "6. Квалификационные требования к поставщику", level=1)
        for q in quals:
            _add_bullet(doc, str(q))

    # 7. Документы
    req_docs = tz.get("documents_required") or []
    if req_docs:
        _add_heading(doc, "7. Перечень документов", level=1)
        for d in req_docs:
            _add_bullet(doc, str(d))

    # 8. Критерии оценки
    if tz.get("evaluation_criteria"):
        _add_heading(doc, "8. Критерии оценки заявок", level=1)
        crit = tz["evaluation_criteria"]
        if isinstance(crit, dict):
            for k, v in crit.items():
                _add_para(doc, f"{k}: {v}")
        else:
            _add_para(doc, str(crit))

    # 9. Red flags
    flags = tz.get("red_flags") or []
    if flags:
        _add_heading(doc, "9. Замечания (проверьте)", level=1)
        for f in flags:
            _add_bullet(doc, str(f))

    # 10. Warnings
    warnings = tz.get("warnings") or []
    if warnings:
        _add_heading(doc, "10. Рекомендации", level=1)
        for w in warnings:
            _add_bullet(doc, str(w))

    # 11. Соответствие закону
    if tz.get("legal_compliance"):
        _add_heading(doc, "11. Соответствие законодательству", level=1)
        comp = tz["legal_compliance"]
        comp_label = {
            "ok": "✓ Соответствует",
            "review": "⚠ Требует проверки",
            "violation": "✗ Есть нарушения",
        }.get(comp, comp)
        _add_para(doc, comp_label, bold=True)
        if tz.get("compliance_notes"):
            _add_para(doc, tz["compliance_notes"])

    # Подвал
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run("Сформировано автоматически системой Tendr (AI-ассистент для МСБ РК)")
    r.italic = True
    r.font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
