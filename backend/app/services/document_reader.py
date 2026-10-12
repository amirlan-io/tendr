"""Чтение текста из загруженных документов (PDF, DOCX, TXT).

Pipeline:
1. PDF: сначала pypdf. Если мало текста (< 50 chars/page) — это скан,
   делаем OCR через Mistral OCR.
2. DOCX: python-docx. Если падает — fallback на XML-парсинг.
3. TXT/MD: читаем как plain text.
4. PDF с картинками: извлекаем картинки, описываем через Mistral Vision.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from docx import Document
from loguru import logger
from pypdf import PdfReader

from app.core.config import get_settings

# Минимальное количество символов на страницу, чтобы считать, что PDF содержит текст
_MIN_CHARS_PER_PAGE = 50
# Защитные лимиты для официальных вложений и пользовательских файлов. Раньше
# ссылки на эти константы существовали без определений, поэтому PDF/XLSX
# завершались ошибкой до чтения содержимого.
MAX_PDF_PAGES = 120
MAX_EXCEL_ROWS = 5_000
MAX_EXCEL_COLUMNS = 100
MAX_EXCEL_CELLS = 200_000


async def extract_text(file_path: str | Path, *, include_vision: bool = True) -> str:
    """Извлечь текст из файла. Поддержка: .pdf, .docx, .txt, .md, .xlsx, .xls, .csv.

    Для PDF с картинками: извлекаем текст + vision-описания картинок.
    Для Excel: читаем все ячейки по всем листам, форматируем как текст.
    """
    p = Path(file_path)
    suffix = p.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _read_pdf(p)
        elif suffix == ".docx":
            text = _read_docx(p)
        elif suffix in {".xlsx", ".xlsm"}:
            text = await _read_xlsx(p)
        elif suffix == ".xls":
            text = await _read_xls(p)
        elif suffix == ".csv":
            text = await _read_csv(p)
        elif suffix in {".txt", ".md"}:
            text = p.read_text(encoding="utf-8", errors="ignore")
        else:
            text = p.read_text(encoding="utf-8", errors="ignore")

        # Для PDF: добавляем vision-описания картинок (если есть)
        if include_vision and suffix == ".pdf" and text and not text.startswith("["):
            try:
                from app.services.vision import describe_pdf_images

                img_desc = await describe_pdf_images(p)
                if img_desc:
                    text = f"{text}\n\n=== ОПИСАНИЯ КАРТИНОК ИЗ ДОКУМЕНТА ===\n{img_desc}"
            except Exception as e:
                logger.warning("Vision extraction failed: {}", e)

        return text
    except Exception:
        logger.exception("Failed to extract text from {}", p)
        return "[Ошибка чтения файла: формат не поддерживается или файл повреждён.]"


def _read_pdf(p: Path) -> str:
    reader = PdfReader(str(p))
    parts: list[str] = []
    pages = reader.pages[:MAX_PDF_PAGES]
    if len(reader.pages) > MAX_PDF_PAGES:
        parts.append("[Текст обрезан: превышен лимит страниц PDF]")
    for page in pages:
        try:
            text = page.extract_text() or ""
            parts.append(text)
        except Exception:
            parts.append("")

    full = "\n\n".join(parts).strip()

    # Детектор сканов: мало текста на страницу = скорее всего скан
    n_pages = len(reader.pages)
    if n_pages > 0:
        chars_per_page = len(full) / n_pages
        if chars_per_page < _MIN_CHARS_PER_PAGE:
            logger.warning(
                "PDF {} looks like a scan: {} chars / {} pages — running Mistral OCR",
                p,
                len(full),
                n_pages,
            )
            ocr_text = _ocr_pdf_with_mistral(p)
            if ocr_text and len(ocr_text) > len(full):
                logger.info("OCR extracted {} chars", len(ocr_text))
                return ocr_text
            full = (
                "[ВНИМАНИЕ: PDF выглядит как скан, OCR не дал результата. "
                "Попросите пользователя прислать DOCX или текстом.]\n\n" + full
            )

    return full


def _ocr_pdf_with_mistral(p: Path) -> str:
    """OCR через Mistral OCR (mistral-ocr-latest)."""
    settings = get_settings()
    if not settings.llm_api_key:
        logger.warning("Mistral API key not set, OCR unavailable")
        return ""
    try:
        from mistralai.client import Mistral

        client = Mistral(api_key=settings.llm_api_key)
        with open(p, "rb") as f:
            pdf_bytes = f.read()
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        resp = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{pdf_b64}",
            },
            include_image_base64=False,
        )
        texts: list[str] = []
        for page in resp.pages:
            if hasattr(page, "markdown") and page.markdown:
                texts.append(page.markdown)
        return "\n\n".join(texts).strip()
    except Exception as e:
        logger.exception("Mistral OCR failed: {}", e)
        return ""


def _read_docx(p: Path) -> str:
    # 1. Попытка через python-docx
    try:
        doc = Document(str(p))
        parts: list[str] = []
        for para in doc.paragraphs:
            if para.text:
                parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_text = "\t".join(cell.text for cell in row.cells if cell.text)
                if row_text:
                    parts.append(row_text)
        result = "\n".join(parts).strip()
        if result:
            return result
    except Exception as e:
        logger.warning("python-docx failed for {}: {}. Trying XML fallback.", p, e)

    # 2. Fallback: прямой XML-парсинг word/document.xml
    return _read_docx_via_xml(p)


def _read_docx_via_xml(p: Path) -> str:
    """Парсит DOCX как ZIP-архив и извлекает текст из word/document.xml."""
    import re
    import zipfile

    try:
        with zipfile.ZipFile(str(p)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    except (KeyError, zipfile.BadZipFile) as e:
        return f"[Ошибка чтения DOCX: {e}]"

    paragraphs = re.split(r"</w:p>", xml)
    lines: list[str] = []
    for para in paragraphs:
        para_texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", para)
        if para_texts:
            lines.append("".join(para_texts))
    return "\n".join(lines).strip()


async def _read_xlsx(p: Path) -> str:
    """Читает .xlsx (Excel 2007+) — все ячейки по всем листам."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return f"[openpyxl не установлен для чтения {p}]"

    try:
        wb = load_workbook(str(p), data_only=True, read_only=True)
        parts: list[str] = []
        cell_count = 0
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            parts.append(f"\n=== Лист: {sheet_name} ===")
            for row in sheet.iter_rows(values_only=True, max_row=MAX_EXCEL_ROWS, max_col=MAX_EXCEL_COLUMNS):
                cells = [str(c) if c is not None else "" for c in row]
                if any(c for c in cells):
                    cell_count += len(cells)
                    if cell_count > MAX_EXCEL_CELLS:
                        parts.append("[Таблица обрезана: превышен лимит ячеек]")
                        return "\n".join(parts).strip()
                    parts.append(" | ".join(cells))
        return "\n".join(parts).strip()
    except Exception:
        logger.exception("XLSX read failed for {}", p)
        return "[Ошибка чтения XLSX: формат не поддерживается или файл повреждён.]"


async def _read_xls(p: Path) -> str:
    """Читает старый .xls (Excel 97-2003) — нужен xlrd."""
    try:
        import xlrd  # type: ignore
    except ImportError:
        return f"[xlrd не установлен для чтения {p}. Установи: pip install xlrd==1.2.0]"

    try:
        book = xlrd.open_workbook(str(p))
        parts: list[str] = []
        cell_count = 0
        for sheet in book.sheets():
            parts.append(f"\n=== Лист: {sheet.name} ===")
            for row_idx in range(min(sheet.nrows, MAX_EXCEL_ROWS)):
                row = sheet.row_values(row_idx)[:MAX_EXCEL_COLUMNS]
                cells = [str(c) if c else "" for c in row]
                if any(c for c in cells):
                    cell_count += len(cells)
                    if cell_count > MAX_EXCEL_CELLS:
                        parts.append("[Таблица обрезана: превышен лимит ячеек]")
                        return "\n".join(parts).strip()
                    parts.append(" | ".join(cells))
        return "\n".join(parts).strip()
    except Exception:
        logger.exception("XLS read failed for {}", p)
        return "[Ошибка чтения XLS: формат не поддерживается или файл повреждён.]"


async def _read_csv(p: Path) -> str:
    """Читает CSV (с автоопределением разделителя и кодировки)."""
    import csv

    # Попробуем разные кодировки
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            content = p.read_text(encoding=encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    else:
        content = p.read_text(encoding="utf-8", errors="ignore")

    # Определяем разделитель по первой строке
    try:
        dialect = csv.Sniffer().sniff(content[:1024], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # по умолчанию запятая

    reader = csv.reader(io.StringIO(content), dialect=dialect)
    rows = [row for row in reader if row]
    parts = []
    for row in rows[:1000]:  # лимит на 1000 строк
        parts.append(" | ".join(str(c) for c in row))
    return "\n".join(parts)


def get_metadata(file_path: str | Path) -> dict[str, Any]:
    """Метаданные файла для анализа."""
    p = Path(file_path)
    info: dict[str, Any] = {
        "filename": p.name,
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "suffix": p.suffix.lower(),
    }
    if p.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(str(p))
            info["pages"] = len(reader.pages)
            info["metadata"] = {k: str(v) for k, v in (reader.metadata or {}).items()}
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
    return info
