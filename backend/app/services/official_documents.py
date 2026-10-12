"""Безопасная загрузка и чтение официальных вложений лота Госзакупок.

Метаданные файлов приходят только из официального GraphQL API. URL всё равно
проходит строгий allowlist, потому что удалённые адреса нельзя считать
доверенными только из-за источника JSON.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from loguru import logger

from app.services.document_reader import extract_text

_ALLOWED_HOSTS = {
    "goszakup.gov.kz",
    "ows.goszakup.gov.kz",
    "portal.goszakup.gov.kz",
    "v3bl.goszakup.gov.kz",
}
_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".xlsx", ".xls", ".csv"}
_MAX_FILE_BYTES = 20 * 1024 * 1024
_MAX_TOTAL_BYTES = 40 * 1024 * 1024
_MAX_FILES = 8


@dataclass(slots=True)
class ExtractedOfficialDocument:
    name: str
    document_type: str
    url: str
    text: str = ""
    error: str = ""

    @property
    def extracted(self) -> bool:
        return bool(self.text.strip()) and not self.text.lstrip().startswith("[")


def _safe_official_url(raw_url: Any) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in _ALLOWED_HOSTS:
        return None
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        return None
    return value


def _filename(metadata: dict[str, Any]) -> str:
    original = str(metadata.get("original_name") or metadata.get("originalName") or "").strip()
    if original:
        return Path(original).name
    return f"document-{metadata.get('id') or 'official'}.bin"


async def fetch_official_documents(
    files: list[dict[str, Any]],
) -> list[ExtractedOfficialDocument]:
    """Скачать и прочитать ограниченный набор официальных вложений.

    Ошибка отдельного файла не ломает весь анализ: метаданные и понятная
    причина остаются в результате, а анализ помечается как неполный выше по
    pipeline.
    """

    results: list[ExtractedOfficialDocument] = []
    total_bytes = 0
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(35.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": "TendrBot/0.1 (+https://tendr.kz)"},
    ) as client:
        for metadata in files[:_MAX_FILES]:
            name = _filename(metadata)
            document_type = str(
                metadata.get("name_ru")
                or metadata.get("nameRu")
                or "Официальное вложение"
            ).strip()
            url = _safe_official_url(metadata.get("file_path") or metadata.get("filePath"))
            item = ExtractedOfficialDocument(
                name=name,
                document_type=document_type,
                url=url or "",
            )
            results.append(item)
            if not url:
                item.error = "Недопустимый адрес официального файла"
                continue

            suffix = Path(name).suffix.lower()
            if suffix not in _SUPPORTED_SUFFIXES:
                item.error = f"Формат {suffix or 'без расширения'} пока не поддерживается"
                continue

            temp_path: str | None = None
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    item.error = f"Официальный сервер вернул HTTP {response.status_code}"
                    continue
                content_length = int(response.headers.get("content-length") or 0)
                if content_length > _MAX_FILE_BYTES:
                    item.error = "Файл превышает лимит 20 МБ"
                    continue
                content = response.content
                if len(content) > _MAX_FILE_BYTES or total_bytes + len(content) > _MAX_TOTAL_BYTES:
                    item.error = "Превышен безопасный лимит размера вложений"
                    continue
                total_bytes += len(content)

                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
                    temporary.write(content)
                    temp_path = temporary.name
                # Для официального источника берём только извлечённый текст/OCR.
                # Генеративные описания изображений сюда не добавляем: они не
                # являются дословными данными документа.
                text = (await extract_text(temp_path, include_vision=False)).strip()
                if not text or text.startswith("[Ошибка"):
                    item.error = "Не удалось извлечь текст из файла"
                    continue
                item.text = text
            except (httpx.HTTPError, OSError, ValueError) as exc:
                logger.warning("Official document download failed for {}: {}", url, exc)
                item.error = "Не удалось получить или прочитать официальный файл"
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        logger.debug("Could not remove temporary official document {}", temp_path)

    return results

