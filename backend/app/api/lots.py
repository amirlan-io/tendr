"""API endpoints для каталога лотов и партнёрств.

P0: Конкуренция с ets-tender.kz и zakup.gov.kz.
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_id import require_client_id, validate_client_id
from app.core.config import get_settings
from app.db import get_db
from app.db import repo as db_repo
from app.db.models import Analysis, Lot, LotPartnership, User
from app.schemas.lot import (
    LotItem,
    LotSearchRequest,
    LotSearchResult,
    PartnershipRequest,
    PartnershipResponse,
)
from app.services.doc_generator import generate_complaint_docx, generate_report_docx
from app.services.goszakup_parser import GoszakupParser
from app.services.lots import LotAggregator, LotAnalyzer
from app.services.orchestrator import LotOrchestrator, analyze_uploaded_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lots", tags=["lots"])

UPLOAD_READ_CHUNK_SIZE = 64 * 1024
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 200
MAX_ZIP_TOTAL_UNCOMPRESSED = 64 * 1024 * 1024
MAX_ZIP_ENTRY_SIZE = 16 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200.0
MAX_HISTORY_LIMIT = 50
DEFAULT_HISTORY_LIMIT = 20
ALLOWED_DOWNLOAD_KINDS = {"complaint", "report"}


class UploadValidationError(ValueError):
    def __init__(self, code: str, safe_message: str = "INVALID_FILE") -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _normalize_mime(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


async def read_upload_file_safely(
    file: UploadFile,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    chunk_size: int = UPLOAD_READ_CHUNK_SIZE,
) -> bytes:
    """Read an uploaded file in bounded chunks and reject oversize data early."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadValidationError("FILE_TOO_LARGE", "FILE_TOO_LARGE")
        chunks.append(chunk)

    payload = b"".join(chunks)
    if not payload:
        raise UploadValidationError("EMPTY_FILE", "EMPTY_FILE")
    return payload


def _assert_no_zip_path_traversal(name: str) -> None:
    cleaned = name.replace("\\", "/")
    if cleaned.startswith("/") or cleaned.startswith("../") or cleaned == "..":
        raise UploadValidationError("ZIP_PATH_TRAVERSAL", "INVALID_FILE")
    parts = PurePosixPath(cleaned).parts
    if ".." in parts:
        raise UploadValidationError("ZIP_PATH_TRAVERSAL", "INVALID_FILE")


def _validate_zip_container(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos:
                raise UploadValidationError("INVALID_ZIP", "INVALID_FILE")
            if len(infos) > MAX_ZIP_ENTRIES:
                raise UploadValidationError("ZIP_BOMB", "INVALID_FILE")

            total_uncompressed = 0
            for info in infos:
                if info.is_dir():
                    continue
                _assert_no_zip_path_traversal(info.filename)
                if info.flag_bits & 0x1:
                    raise UploadValidationError("ENCRYPTED_ZIP", "INVALID_FILE")
                if info.file_size > MAX_ZIP_ENTRY_SIZE:
                    raise UploadValidationError("ZIP_BOMB", "INVALID_FILE")
                if info.compress_size and info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_ZIP_COMPRESSION_RATIO:
                        raise UploadValidationError("ZIP_BOMB", "INVALID_FILE")
                total_uncompressed += info.file_size

            if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED:
                raise UploadValidationError("ZIP_BOMB", "INVALID_FILE")
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("INVALID_ZIP", "INVALID_FILE") from exc
    except RuntimeError as exc:
        raise UploadValidationError("ZIP_BOMB", "INVALID_FILE") from exc


def _get_supported_extension(filename: str | None) -> str:
    name = os.path.basename(filename or "").strip()
    if not name or name in {".", ".."}:
        raise UploadValidationError("INVALID_FILE_NAME", "INVALID_FILE")
    if name != os.path.basename(name):
        raise UploadValidationError("INVALID_FILE_NAME", "INVALID_FILE")
    if name.count(".") > 1:
        raise UploadValidationError("DOUBLE_EXTENSION", "INVALID_FILE")
    ext = os.path.splitext(name)[1].lower()
    return ext


def validate_upload_file(
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    settings,
) -> None:
    """Проверяет размер, расширение, MIME и сигнатуру загружаемого файла."""
    max_bytes = int(getattr(settings, "max_upload_bytes", MAX_UPLOAD_BYTES))
    if not data:
        raise UploadValidationError("EMPTY_FILE", "EMPTY_FILE")
    if len(data) > max_bytes:
        raise UploadValidationError("FILE_TOO_LARGE", "FILE_TOO_LARGE")

    ext = _get_supported_extension(filename)
    allowed_ext = {".pdf", ".docx", ".txt", ".csv", ".xlsx", ".xls"}
    if ext not in allowed_ext:
        raise UploadValidationError("UNSUPPORTED_FILE_TYPE", "UNSUPPORTED_FILE_TYPE")

    mime = _normalize_mime(content_type)
    allowed_mime = {
        ".pdf": {"application/pdf"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".txt": {"text/plain", "application/octet-stream"},
        ".csv": {"text/csv", "application/csv", "application/octet-stream"},
        ".xlsx": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        },
        ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    }
    if mime and mime not in allowed_mime.get(ext, set()):
        raise UploadValidationError("MIME_MISMATCH", "INVALID_FILE")

    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UploadValidationError("INVALID_PDF", "INVALID_FILE")
    elif ext in {".docx", ".xlsx"}:
        if not data.startswith(b"PK"):
            raise UploadValidationError("INVALID_ZIP", "INVALID_FILE")
        _validate_zip_container(data)
    elif ext == ".xls":
        if not data.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
            raise UploadValidationError("INVALID_XLS", "INVALID_FILE")
    elif ext in {".txt", ".csv"}:
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("INVALID_TEXT_ENCODING", "INVALID_FILE") from exc


def _get_api_token() -> str:
    settings = get_settings()
    return getattr(settings, "goszakup_api_token", "") or ""


def _parse_red_flags(raw: str | None) -> list[str]:
    """Парсит JSON-список red flags из БД."""
    if not raw:
        return []
    try:
        import json

        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []


def _sanitize_csv_cell(value: object) -> str:
    """Гарантирует безопасный CSV/Excel экспорт без formula injection."""
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if text and text[0] in {"=", "+", "-", "@", "\t"}:
        text = "'" + text
    return text


def _safe_history_item(item: Analysis) -> dict:
    result = item.result_json or {}
    lot = result.get("lot") if isinstance(result, dict) else {}
    legal = result.get("legal") if isinstance(result, dict) else {}
    if not isinstance(lot, dict):
        lot = {}
    if not isinstance(legal, dict):
        legal = {}

    created_at = item.created_at.isoformat() if getattr(item, "created_at", None) else None
    return {
        "lot_id": str(item.lot_id),
        "title": str((lot.get("title") or item.title or "")).strip(),
        "customer": str((lot.get("customer") or item.customer or "")).strip(),
        "method": str((lot.get("method") or item.method or "")).strip(),
        "overall_risk": str((legal.get("overall_risk") or item.overall_risk or "needs_review")).strip(),
        "n_requirements": int(item.n_requirements or len((lot.get("requirements") or []))),
        "n_red_flags": int(item.n_red_flags or len((lot.get("red_flags") or []))),
        "created_at": created_at,
    }


def _safe_download_filename(kind: str, lot_id: int | str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(kind)).strip("_") or "file"
    safe_lot = re.sub(r"[^A-Za-z0-9_-]+", "_", str(lot_id)).strip("_") or "lot"
    return f"{slug}_{safe_lot}.docx"


@router.post("/search", response_model=LotSearchResult)
async def search_lots(
    req: LotSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> LotSearchResult:
    """
    Поиск лотов со всех площадок (zakup.gov.kz, ets-tender.kz, ...).

    Пока работает в mock-режиме (демо-данные). Когда придёт токен goszakup
    и подключим парсеры других площадок — будут реальные данные.
    """
    settings = get_settings()
    api_token = _get_api_token()
    # Реальный токен — не mock-заглушка
    is_mock = not api_token or api_token.startswith("mock")

    aggregator = LotAggregator(api_token=api_token)
    parsed_lots = await aggregator.get_lots(
        query=req.query,
        region=req.region,
        platform=req.platform,
        min_amount=req.min_amount_kzt,
        max_amount=req.max_amount_kzt,
        category=req.category,
        customer_bin=req.customer_bin,
        customer_bin_like=req.customer_bin_like,
        only_with_amount=req.only_with_amount,
        use_graphql=req.use_graphql,
        limit=req.limit,
    )


    # Сохраняем в БД (кэш)
    saved_lots: list[Lot] = []
    for pl in parsed_lots:
        existing = await db.execute(
            select(Lot).where(Lot.source == pl.source, Lot.source_id == pl.source_id)
        )
        lot = existing.scalar_one_or_none()
        if lot is None:
            lot = Lot(
                source=pl.source,
                source_id=pl.source_id,
                source_url=pl.source_url,
                title=pl.title,
                description=pl.description,
                category=pl.category,
                procurement_method=pl.procurement_method,
                platform=pl.platform,
                amount_kzt=pl.amount_kzt,
                price_per_unit=pl.price_per_unit,
                region=pl.region,
                delivery_address=pl.delivery_address,
                publish_date=pl.publish_date,
                deadline_date=pl.deadline_date,
                organizer=pl.organizer,
                organizer_bin=pl.organizer_bin,
                status=pl.status,
                raw_data=str(pl.raw_data)[:5000],  # truncate
            )
            db.add(lot)
            saved_lots.append(lot)
        else:
            # Обновляем изменившиеся поля
            lot.title = pl.title
            lot.amount_kzt = pl.amount_kzt
            lot.deadline_date = pl.deadline_date
            lot.status = pl.status
            saved_lots.append(lot)

    await db.commit()
    for lot in saved_lots:
        await db.refresh(lot)

    # AI-анализ (P0-3): Documenter + Legal — ОПЦИОНАЛЬНО (выкл по умолчанию)
    # Включается флагом with_ai=true, ограничено ai_limit лотами
    # По умолчанию OFF — анализ занимает 30-60 сек на лот и перегружает LLM
    if req.with_ai and req.ai_limit > 0:
        analyzer = LotAnalyzer()
        lots_to_analyze = [
            lot for lot in saved_lots if not lot.ai_processed
        ][: req.ai_limit]
        if lots_to_analyze:
            try:
                # Параллельный анализ (max 3 одновременно чтобы не перегружать LLM)
                results = await analyzer.analyze_batch(
                    [
                        {
                            "id": lot.id,
                            "title": lot.title,
                            "description": lot.description,
                            "amount_kzt": lot.amount_kzt,
                            "region": lot.region,
                            "category": lot.category,
                            "organizer": lot.organizer,
                            "delivery_address": lot.delivery_address,
                            "deadline_date": lot.deadline_date,
                        }
                        for lot in lots_to_analyze
                    ],
                    max_concurrent=3,
                )
                for lot, (summary, red_flags, match_score) in zip(
                    lots_to_analyze, results
                ):
                    lot.ai_summary = summary
                    lot.ai_red_flags = str(red_flags)[:5000]  # JSON list
                    lot.ai_match_score = match_score
                    lot.ai_processed = True
                await db.commit()
                for lot in lots_to_analyze:
                    await db.refresh(lot)
            except Exception as e:
                logger.exception(f"[lots] AI analyze failed: {e}")
                # Не критично — лоты работают и без AI

    # Конвертируем в response schema с вычислением days_until_deadline
    from datetime import datetime

    items: list[LotItem] = []
    for lot in saved_lots:
        days_left = None
        is_urgent = False
        deadline_time_str = None
        if lot.deadline_date:
            now = datetime.now(lot.deadline_date.tzinfo)
            delta_days = (lot.deadline_date - now).days
            delta_seconds = (lot.deadline_date - now).total_seconds()
            days_left = max(0, delta_days)
            is_urgent = days_left <= 3
            # Формируем человеко-читаемое время дедлайна
            time_str = lot.deadline_date.strftime("%H:%M")
            if delta_days == 0:
                if delta_seconds > 0:
                    # сегодня, до HH:MM
                    hours_left = int(delta_seconds // 3600)
                    if hours_left > 0:
                        deadline_time_str = f"сегодня до {time_str} (осталось {hours_left}ч)"
                    else:
                        mins_left = max(1, int(delta_seconds // 60))
                        deadline_time_str = f"сегодня до {time_str} (⏰ {mins_left} мин!)"
                else:
                    deadline_time_str = f"просрочен ({time_str})"
            elif delta_days == 1:
                deadline_time_str = f"завтра до {time_str}"
            elif delta_days <= 7:
                deadline_time_str = lot.deadline_date.strftime("%a %d.%m %H:%M")
            else:
                deadline_time_str = lot.deadline_date.strftime("%d.%m.%Y %H:%M")

        # Фильтр по urgency
        if req.only_urgent and not is_urgent:
            continue

        items.append(
            LotItem(
                id=lot.id,
                source=lot.source,
                source_id=lot.source_id,
                title=lot.title,
                description=lot.description,
                category=lot.category,
                procurement_method=lot.procurement_method,
                platform=lot.platform,
                amount_kzt=lot.amount_kzt,
                price_per_unit=lot.price_per_unit,
                region=lot.region,
                delivery_address=lot.delivery_address,
                publish_date=lot.publish_date,
                deadline_date=lot.deadline_date,
                organizer=lot.organizer,
                organizer_bin=lot.organizer_bin,
                status=lot.status,
                source_url=lot.source_url,
                ai_summary=lot.ai_summary,
                ai_red_flags=_parse_red_flags(lot.ai_red_flags),
                ai_match_score=lot.ai_match_score,
                days_until_deadline=days_left,
                is_urgent=is_urgent,
                deadline_time_str=deadline_time_str,
            )
        )

    # Сортировка: сначала срочные, потом по дате публикации (свежие выше)
    items.sort(
        key=lambda x: (
            not x.is_urgent,  # urgent first
            -(x.publish_date.timestamp() if x.publish_date else 0),
        )
    )

    return LotSearchResult(
        lots=items,
        total=len(items),
        source="zakup.gov.kz (mock)" if is_mock else "zakup.gov.kz",
        is_mock=is_mock,
    )


@router.get("/history")
async def get_lot_history(
    client_id: str = Depends(require_client_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Список истории анализов только текущего клиента."""
    user = await db_repo.get_user_by_web_id(db, client_id)
    if not user:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    rows = await db_repo.get_user_history(db, user.id, limit=limit, offset=offset)
    items = [_safe_history_item(item) for item in rows]
    total = await db_repo.get_user_history(db, user.id, limit=MAX_HISTORY_LIMIT, offset=0)
    return {
        "items": items,
        "total": len(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{lot_id}/download")
async def download_lot_document(
    lot_id: int,
    kind: str = Query(..., min_length=1, max_length=32),
    client_id: str = Depends(require_client_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Скачать безопасный документ жалобы или отчёта по лоту текущего клиента."""
    normalized_kind = (kind or "").strip().lower()
    if normalized_kind not in ALLOWED_DOWNLOAD_KINDS:
        raise HTTPException(status_code=400, detail="INVALID_DOWNLOAD_KIND")

    user = await db_repo.get_user_by_web_id(db, client_id)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")

    analysis = await db_repo.get_analysis_by_lot(db, user.id, str(lot_id))
    if not analysis:
        raise HTTPException(status_code=404, detail="Not found")

    result = analysis.result_json or {}
    lot = result.get("lot") if isinstance(result, dict) else {}
    legal = result.get("legal") if isinstance(result, dict) else {}
    if not isinstance(lot, dict):
        lot = {}
    if not isinstance(legal, dict):
        legal = {}

    filename = _safe_download_filename(normalized_kind, lot_id)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }

    if normalized_kind == "complaint":
        complaint = legal.get("complaint_draft")
        if not complaint:
            raise HTTPException(status_code=404, detail="Not found")
        payload = generate_complaint_docx(
            str(lot_id),
            complaint,
            lot_title=str(lot.get("title") or analysis.title or ""),
        )
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        if not lot and not legal:
            raise HTTPException(status_code=404, detail="Not found")
        payload = generate_report_docx(
            {
                "lot_id": str(lot_id),
                "title": str(lot.get("title") or analysis.title or ""),
                "customer": str(lot.get("customer") or analysis.customer or ""),
                "method": str(lot.get("method") or analysis.method or ""),
                "budget_kzt": lot.get("budget_kzt") or analysis.budget_kzt,
                "deadline": lot.get("deadline") or analysis.deadline,
                "requirements": lot.get("requirements") or [],
                "red_flags": lot.get("red_flags") or [],
                "summary": lot.get("summary") or "",
                "documents_required": lot.get("documents_required") or [],
            },
            legal,
        )
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="download_", suffix=".docx", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as fh:
            content = fh.read()
        return Response(
            content=content,
            media_type=media_type,
            headers=headers,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.get("/{lot_id}", response_model=LotItem)
async def get_lot(lot_id: int, db: AsyncSession = Depends(get_db)) -> LotItem:
    """Получить один лот по ID."""
    lot = await db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    from datetime import datetime

    days_left = None
    is_urgent = False
    deadline_time_str = None
    if lot.deadline_date:
        now = datetime.now(lot.deadline_date.tzinfo)
        delta_days = (lot.deadline_date - now).days
        delta_seconds = (lot.deadline_date - now).total_seconds()
        days_left = max(0, delta_days)
        is_urgent = days_left <= 3
        time_str = lot.deadline_date.strftime("%H:%M")
        if delta_days == 0:
            if delta_seconds > 0:
                hours_left = int(delta_seconds // 3600)
                if hours_left > 0:
                    deadline_time_str = f"сегодня до {time_str} (осталось {hours_left}ч)"
                else:
                    mins_left = max(1, int(delta_seconds // 60))
                    deadline_time_str = f"сегодня до {time_str} (⏰ {mins_left} мин!)"
            else:
                deadline_time_str = f"просрочен ({time_str})"
        elif delta_days == 1:
            deadline_time_str = f"завтра до {time_str}"
        elif delta_days <= 7:
            deadline_time_str = lot.deadline_date.strftime("%a %d.%m %H:%M")
        else:
            deadline_time_str = lot.deadline_date.strftime("%d.%m.%Y %H:%M")

    return LotItem(
        id=lot.id,
        source=lot.source,
        source_id=lot.source_id,
        title=lot.title,
        description=lot.description,
        category=lot.category,
        procurement_method=lot.procurement_method,
        platform=lot.platform,
        amount_kzt=lot.amount_kzt,
        price_per_unit=lot.price_per_unit,
        region=lot.region,
        delivery_address=lot.delivery_address,
        publish_date=lot.publish_date,
        deadline_date=lot.deadline_date,
        organizer=lot.organizer,
        organizer_bin=lot.organizer_bin,
        status=lot.status,
        source_url=lot.source_url,
        ai_summary=lot.ai_summary,
        ai_red_flags=_parse_red_flags(lot.ai_red_flags),
        ai_match_score=lot.ai_match_score,
        days_until_deadline=days_left,
        is_urgent=is_urgent,
        deadline_time_str=deadline_time_str,
    )


class AnalyzeLotRequest(BaseModel):
    """Запрос на полный AI-анализ лота по URL."""

    url: str = Field(..., description="URL лота на zakup.gov.kz / v3bl.goszakup.gov.kz")


@router.post("/analyze")
async def analyze_lot_url(
    req: AnalyzeLotRequest,
    client_id: str = Depends(require_client_id),
    db: AsyncSession = Depends(get_db),
):
    """Полный AI-анализ лота: Documenter + Legal + Customer Score + Margin.

    Используется страницей /analyze.
    """
    from app.services.orchestrator import LotOrchestrator

    import re

    url = req.url.strip()
    try:
        source_id = GoszakupParser._normalize_reference(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Поддерживаются только ссылки goszakup.gov.kz") from exc
    if not source_id:
        raise HTTPException(status_code=400, detail="Невозможно извлечь ID лота из ссылки")

    # Получаем или создаём пользователя только после успешной валидации ссылки.
    cid = client_id
    user = await db_repo.get_user_by_web_id(db, cid)
    if not user:
        user = await db_repo.get_or_create_user(db, web_client_id=cid)

    quota = await db_repo.get_user_quota(db, user.id)
    is_pilot = bool(quota.get("is_pilot", False))
    free_limit = int(quota.get("monthly_limit") or quota.get("limit") or 3)
    used_this_month = int(quota.get("used_this_month") or quota.get("used") or 0)

    from app.schemas.lot import LotCreate

    reservation = None
    lot_create = LotCreate(source_url=url, source_id=source_id or "0")
    orchestrator = LotOrchestrator(session=db)
    try:
        reservation = await db_repo.reserve_user_quota(
            db,
            user.id,
            operation_key=f"lot:{source_id}",
            amount=1,
            ttl_seconds=300,
            limit=free_limit,
        )
        result = await orchestrator.analyze_lot(
            lot_create,
            user_id=user.id,
            is_pilot=is_pilot,
            used_this_month=used_this_month + 1,
            free_limit=free_limit,
        )
        await db_repo.confirm_user_quota(db, user.id, reservation_key=reservation["reservation_key"])
    except db_repo.QuotaLimitExceeded as exc:
        logger.warning("[analyze] quota exceeded user=%s", user.id)
        raise HTTPException(status_code=429, detail="QUOTA_EXCEEDED") from exc
    except Exception:
        logger.exception("[analyze] orchestrator failed")
        if reservation:
            await db_repo.release_user_quota(db, user.id, reservation_key=reservation["reservation_key"])
        raise HTTPException(status_code=500, detail="ANALYSIS_FAILED")

    # Сохраняем в историю
    try:
        from datetime import datetime as dt

        if result.lot and result.lot.lot_id:
            await db_repo.push_history(
                db,
                user.id,
                {
                    "lot_id": result.lot.lot_id,
                    "title": result.lot.title,
                    "url": req.url,
                    "created_at": dt.utcnow().isoformat(),
                    "overall_risk": result.legal.overall_risk
                    if result.legal
                    else None,
                    "n_requirements": len(result.lot.requirements or []),
                    "n_red_flags": len(result.lot.red_flags or []),
                },
            )
    except Exception as e:
        logger.warning(f"[analyze] history push failed: {e}")

    return result.model_dump()


@router.post("/analyze-upload")
async def analyze_lot_upload(
    client_id: str = Depends(require_client_id),
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = None,
):
    """Анализ ТЗ из загруженного файла (PDF/DOCX/TXT/XLSX/CSV).

    Используется Telegram-ботом и веб-интерфейсом когда нет URL лота.
    """
    if file is None:
        # FastAPI может не подхватить file если поле названо иначе — пробуем
        # стандартный механизм multipart.
        raise HTTPException(status_code=400, detail="Файл не передан (поле file)")

    payload = None
    try:
        payload = await read_upload_file_safely(file, max_bytes=get_settings().max_upload_bytes)
        validate_upload_file(
            filename=file.filename,
            content_type=file.content_type,
            data=payload,
            settings=get_settings(),
        )
    except UploadValidationError as exc:
        if exc.code == "FILE_TOO_LARGE":
            raise HTTPException(status_code=413, detail="FILE_TOO_LARGE") from exc
        raise HTTPException(status_code=422, detail=exc.safe_message) from exc

    # Получаем или создаём пользователя только после успешной валидации файла
    cid = client_id
    user = await db_repo.get_user_by_web_id(db, cid)
    if not user:
        user = await db_repo.get_or_create_user(db, web_client_id=cid)

    quota = await db_repo.get_user_quota(db, user.id)
    is_pilot = bool(quota.get("is_pilot", False))
    free_limit = int(quota.get("monthly_limit") or quota.get("limit") or 3)
    used_this_month = int(quota.get("used_this_month") or quota.get("used") or 0)

    suffix_map = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "text/plain": ".txt",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
        "text/csv": ".csv",
    }
    suffix = suffix_map.get((file.content_type or "").split(";", 1)[0].lower(), os.path.splitext(file.filename or "")[1].lower() or ".bin")
    tmp_file = tempfile.NamedTemporaryFile(prefix="upload_", suffix=suffix, delete=False)
    tmp_path = tmp_file.name
    reservation = None
    try:
        with tmp_file:
            tmp_file.write(payload)
        reservation = await db_repo.reserve_user_quota(
            db,
            user.id,
            operation_key=f"upload:{file.filename or 'file'}",
            amount=1,
            ttl_seconds=300,
            limit=free_limit,
        )
        result = await analyze_uploaded_file(
            tmp_path,
            user_id=user.id,
            is_pilot=is_pilot,
            used_this_month=used_this_month + 1,
            free_limit=free_limit,
            session=db,
        )
        await db_repo.confirm_user_quota(db, user.id, reservation_key=reservation["reservation_key"])
    except db_repo.QuotaLimitExceeded as exc:
        logger.warning("[analyze-upload] quota exceeded user=%s", user.id)
        raise HTTPException(status_code=429, detail="QUOTA_EXCEEDED") from exc
    except Exception:
        logger.exception("[analyze-upload] failed")
        if reservation:
            await db_repo.release_user_quota(db, user.id, reservation_key=reservation["reservation_key"])
        raise HTTPException(status_code=500, detail="FILE_PROCESSING_FAILED")
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass

    # Сохраняем в историю
    try:
        from datetime import datetime as dt

        if result.lot and result.lot.lot_id:
            await db_repo.push_history(
                db,
                user.id,
                {
                    "lot_id": result.lot.lot_id,
                    "title": result.lot.title,
                    "url": f"upload:{file.filename}",
                    "created_at": dt.utcnow().isoformat(),
                    "overall_risk": result.legal.overall_risk if result.legal else None,
                    "n_requirements": len(result.lot.requirements or []),
                    "n_red_flags": len(result.lot.red_flags or []),
                },
            )
    except Exception as e:
        logger.warning(f"[analyze-upload] history push failed: {e}")

    return result.model_dump()


@router.post("/{lot_id}/partnership", response_model=PartnershipResponse)
async def create_partnership(
    lot_id: int,
    req: PartnershipRequest,
    client_id: str = Depends(require_client_id),
    db: AsyncSession = Depends(get_db),
) -> PartnershipResponse:
    """
    Создать заявку на партнёрство (B2B matchmaking).

    Это наш USP против конкурентов:
    - supplier: "Могу поставить товар/услугу"
    - investor: "Могу профинансировать"
    - applicant: "Хочу подать заявку"
    - partner: "Готов к любой форме сотрудничества"
    """
    lot = await db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    # Получаем или создаём пользователя
    cid = client_id
    user = await db_repo.get_user_by_web_id(db, cid)
    if not user:
        user = await db_repo.get_or_create_user(db, web_client_id=cid)

    # Проверяем что нет дубля
    existing = await db.execute(
        select(LotPartnership).where(
            LotPartnership.lot_id == lot_id,
            LotPartnership.user_id == user.id,
            LotPartnership.role == req.role,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="Partnership request already exists for this role"
        )

    partnership = LotPartnership(
        lot_id=lot_id,
        user_id=user.id,
        role=req.role,
        message=req.message,
        contact=req.contact,
        status="active",
    )
    db.add(partnership)
    await db.commit()
    await db.refresh(partnership)

    logger.info(f"[Partnership] new request: lot={lot_id} user={user.id} role={req.role}")

    return PartnershipResponse(
        id=partnership.id,
        lot_id=partnership.lot_id,
        role=partnership.role,
        status=partnership.status,
        created_at=partnership.created_at,
    )


@router.get("/{lot_id}/partnerships")
async def list_partnerships(lot_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Список заявок партнёрства по лоту (для организатора)."""
    lot = await db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")

    partnerships = await db.execute(select(LotPartnership).where(LotPartnership.lot_id == lot_id))
    items = [
        {
            "id": p.id,
            "role": p.role,
            "message": p.message,
            "contact": p.contact,
            "status": p.status,
            "created_at": p.created_at.isoformat(),
        }
        for p in partnerships.scalars().all()
    ]
    return {"lot_id": lot_id, "partnerships": items, "total": len(items)}


@router.get("/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db)) -> dict:
    """Статистика по каталогу: сколько лотов всего, по платформам, по статусам."""
    from sqlalchemy import func

    total = await db.execute(select(func.count(Lot.id)))
    total = total.scalar() or 0

    # По площадкам
    platforms = await db.execute(select(Lot.platform, func.count(Lot.id)).group_by(Lot.platform))
    by_platform = {p: c for p, c in platforms.all() if p}

    # По статусам
    statuses = await db.execute(select(Lot.status, func.count(Lot.id)).group_by(Lot.status))
    by_status = {s: c for s, c in statuses.all() if s}

    # Сумма по активным лотам
    from sqlalchemy import case

    total_amount = await db.execute(
        select(func.sum(Lot.amount_kzt)).where(
            Lot.status.in_(["Опубликован", "Приём заявок", "Обсуждение"])
        )
    )
    total_amount = total_amount.scalar() or 0

    return {
        "total_lots": total,
        "by_platform": by_platform,
        "by_status": by_status,
        "total_active_amount_kzt": float(total_amount),
    }
