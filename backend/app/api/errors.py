"""API приёма ошибок от клиента + перехват необработанных на сервере.

/api/errors принимает отчёты из браузера и пересылает владельцу.
/api/errors/test — ручная проверка канала (без реальной ошибки).

Секреты и контакты вычищаются ДО отправки: см. services.error_reporter.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import require_admin_key
from app.core.supabase_auth import get_optional_supabase_user
from app.db import get_db
from app.services.error_reporter import get_reporter, scrub, scrub_payload

router = APIRouter(prefix="/errors", tags=["errors"])


class ErrorReport(BaseModel):
    """Отчёт об ошибке из браузера.

    Ограничения по длине — и для защиты от спама, и потому что длинные
    тексты в Telegram всё равно нечитаемы.
    """

    name: str = Field(default="Error", max_length=120)
    message: str = Field(default="", max_length=2000)
    stack: str = Field(default="", max_length=4000)
    where: str = Field(default="", max_length=300)
    source: str = Field(default="frontend", max_length=24)
    context: dict[str, Any] = Field(default_factory=dict)
    user_hint: str = Field(default="", max_length=200)


@router.post("")
async def report_error(
    payload: ErrorReport,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Принять ошибку из клиента. Всегда отвечает 200.

    Отвечать ошибкой на ошибку бессмысленно: клиент не сможет об этом
    узнать, а фронтенд начнёт ретраить и усилит шторм.
    """
    user = await get_optional_supabase_user(request)
    hint = payload.user_hint or (user.email if user else "")
    report = {
        "name": payload.name,
        "message": payload.message,
        "stack": payload.stack,
        "where": payload.where,
        "source": payload.source,
        "context": scrub_payload(payload.context),
        "user_hint": scrub(hint),
    }
    reporter = get_reporter()
    delivered = await reporter.report(report)
    return JSONResponse(
        {"ok": True, "delivered": delivered},
        status_code=200,
    )


@router.post("/test")
async def test_channel(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    _admin: None = Depends(require_admin_key),
) -> JSONResponse:
    """Проверить, доходит ли уведомление. Без настоящей ошибки.

    Требует админ-ключа: эндпоинт отправляет сообщение в закрытый Telegram-канал,
    а лимит отправок общий на инстанс, поэтому анонимные вызовы выжигали
    канал и заглушали настоящие ошибки (аудит 2026-10-03, P2 abuse).
    """
    reporter = get_reporter()
    configured = bool(reporter.enabled and reporter.bot_token and reporter.admin_ids)
    delivered = False
    if configured:
        delivered = await reporter.report(
            {
                "name": "ТестКанала",
                "message": "Проверка пересылки ошибок. Если вы это видите — канал работает.",
                "source": "backend",
                "where": "/api/errors/test",
            }
        )
    return JSONResponse(
        {
            "ok": True,
            "configured": configured,
            "delivered": delivered,
            "admins": len(reporter.admin_ids),
            # Показываем фактический результат, а не только наличие
            # настроек: иначе легко принять «настроено» за «доставлено».
            "hint": (
                "Уведомление доставлено"
                if delivered
                else (
                    "Канал настроен, но Telegram не принял сообщение — проверьте BOT_TOKEN"
                    if configured
                    else "Канал не настроен: нужны BOT_TOKEN и ADMIN_TELEGRAM_IDS в .env"
                )
            ),
        },
        status_code=200,
    )
