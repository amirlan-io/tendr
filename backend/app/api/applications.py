"""Application API: генерация заявок на участие + калькулятор цены."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.application_generator import (
    calculate_margin,
    generate_application_docx,
)
from app.schemas.lot import (
    ApplicationRequest,
    MarginCalculationRequest,
    MarginCalculationResult,
)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/generate-docx")
async def generate_docx(payload: ApplicationRequest) -> StreamingResponse:
    """Сгенерировать DOCX заявки на участие.

    Возвращает готовый файл для скачивания.
    """
    lot_info = None
    if payload.lot_id or payload.lot_title:
        lot_info = {"lot_id": payload.lot_id or "", "title": payload.lot_title or ""}

    content = generate_application_docx(payload, lot_info)

    # Используем ASCII-only filename + UTF-8 через filename*
    safe_name = "supplier"
    filename = f"zayavka_{safe_name}.docx"
    utf8_filename = f"zayavka_{payload.supplier_name[:30]}.docx".encode("utf-8").decode(
        "latin-1", errors="replace"
    )

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{filename}\"; filename*=UTF-8''{utf8_filename}"
            )
        },
    )


@router.post("/calculate-margin", response_model=MarginCalculationResult)
async def calculate(payload: MarginCalculationRequest) -> MarginCalculationResult:
    """Рассчитать оптимальную цену для участия в лоте.

    Учитывает:
    - Себестоимость
    - Логистику и накладные расходы
    - НДС
    - Желаемую маржу
    - Цену конкурента (если известна)
    """
    return calculate_margin(payload)
