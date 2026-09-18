"""Эндпоинты аккаунта: квоты, discovery-подписки, профиль."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_id import validate_client_id
from app.db import get_db
from app.db import repo as db_repo
from app.db.models import Analysis, DiscoverySubscription, User

router = APIRouter(prefix="/account", tags=["account"])


def _cid(request: Request) -> str:
    raw = request.cookies.get("tendr_cid") or request.headers.get("X-Client-Id")
    if raw is None:
        return ""
    if not validate_client_id(raw):
        return ""
    return raw


def require_admin_key(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    from app.core.config import get_settings

    configured = (get_settings().admin_api_key or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        raise HTTPException(status_code=401, detail="Invalid admin key")


async def _user(session: AsyncSession, request: Request):
    cid = _cid(request)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid client identifier")
    user = await db_repo.get_user_by_web_id(session, cid)
    if not user:
        user = await db_repo.get_or_create_user(session, web_client_id=cid)
    return user


@router.get("/quota")
async def get_quota(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Текущая квота пользователя."""
    user = await _user(session, request)
    quota = await db_repo.get_user_quota(session, user.id)
    quota["user_id"] = user.id
    return quota


class UpdateProfileRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None
    bin: str | None = Field(default=None, description="БИН организации (12 цифр)")
    language: str | None = Field(default=None, pattern="^(ru|kk)$")


@router.patch("/profile")
async def update_profile(
    payload: UpdateProfileRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Обновить профиль пользователя."""
    user = await _user(session, request)
    if payload.email is not None:
        user.email = payload.email
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.company_name is not None:
        user.company_name = payload.company_name
    if payload.bin is not None:
        user.bin = payload.bin
    if payload.language is not None:
        user.language = payload.language
    await session.flush()
    return {"ok": True, "user_id": user.id}


class CreateDiscoveryRequest(BaseModel):
    keywords: str = Field(..., description="Ключевые слова через запятую")
    category: str | None = None
    region: str | None = None
    min_budget_kzt: float | None = None
    max_budget_kzt: float | None = None
    channel: str = Field(default="telegram", pattern="^(telegram|email)$")


@router.post("/discovery/subscribe")
async def discovery_subscribe(
    payload: CreateDiscoveryRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Подписаться на уведомления о новых лотах по ключевым словам."""
    user = await _user(session, request)
    sub = DiscoverySubscription(
        user_id=user.id,
        keywords=payload.keywords,
        category=payload.category,
        region=payload.region,
        min_budget_kzt=payload.min_budget_kzt,
        max_budget_kzt=payload.max_budget_kzt,
        channel=payload.channel,
        is_active=True,
    )
    session.add(sub)
    await session.flush()
    return {"ok": True, "subscription_id": sub.id}


@router.get("/discovery/list")
async def discovery_list(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Список активных discovery-подписок."""
    user = await _user(session, request)
    from sqlalchemy import select

    stmt = select(DiscoverySubscription).where(
        DiscoverySubscription.user_id == user.id,
        DiscoverySubscription.is_active == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    items = result.scalars().all()
    return {
        "items": [
            {
                "id": it.id,
                "keywords": it.keywords,
                "category": it.category,
                "region": it.region,
                "min_budget_kzt": it.min_budget_kzt,
                "max_budget_kzt": it.max_budget_kzt,
                "channel": it.channel,
                "created_at": it.created_at.isoformat(),
            }
            for it in items
        ]
    }


@router.delete("/discovery/{sub_id}")
async def discovery_unsubscribe(
    sub_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Отписаться от уведомлений."""
    user = await _user(session, request)
    sub = await session.get(DiscoverySubscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    sub.is_active = False
    return {"ok": True}


# ---------- Admin endpoints (только для владельца/тестирования) ----------


class SetPilotRequest(BaseModel):
    telegram_id: int | None = None
    web_client_id: str | None = None
    is_pilot: bool = True


@router.post("/admin/set-pilot")
async def admin_set_pilot(
    payload: SetPilotRequest,
    _admin: None = Depends(require_admin_key),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сделать юзера пилотным (безлимит). Для админа/тестирования.

    В будущем — закрыть паролем/ролью.
    """
    from sqlalchemy import update

    if not payload.telegram_id and not payload.web_client_id:
        raise HTTPException(
            status_code=400,
            detail="Нужен telegram_id или web_client_id",
        )

    stmt = update(User).values(is_pilot=payload.is_pilot)
    if payload.telegram_id:
        stmt = stmt.where(User.telegram_id == payload.telegram_id)
    else:
        stmt = stmt.where(User.web_client_id == payload.web_client_id)
    result = await session.execute(stmt)

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    return {"ok": True, "updated": result.rowcount, "is_pilot": payload.is_pilot}


class ResetQuotaRequest(BaseModel):
    telegram_id: int | None = None
    web_client_id: str | None = None


@router.post("/admin/reset-quota")
async def admin_reset_quota(
    payload: ResetQuotaRequest,
    _admin: None = Depends(require_admin_key),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сбросить счётчик использований в этом месяце (для теста).

    В будущем — удалить этот эндпоинт или закрыть.
    """
    from sqlalchemy import and_, delete, func, select

    if not payload.telegram_id and not payload.web_client_id:
        raise HTTPException(
            status_code=400,
            detail="Нужен telegram_id или web_client_id",
        )

    user_stmt = select(User)
    if payload.telegram_id:
        user_stmt = user_stmt.where(User.telegram_id == payload.telegram_id)
    else:
        user_stmt = user_stmt.where(User.web_client_id == payload.web_client_id)
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Удаляем все анализы за текущий месяц
    from datetime import datetime

    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1)
    await session.execute(
        delete(Analysis).where(
            and_(Analysis.user_id == user.id, Analysis.created_at >= start_of_month)
        )
    )
    return {"ok": True, "user_id": user.id, "reset_for_month": now.strftime("%Y-%m")}
