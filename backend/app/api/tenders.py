"""API персонализации тендеров «подобрано для вас» (F8, ТЗ §7).

Маршруты: /api/tenders/*
Скоринг v1 считается в коде поверх существующего поиска лотов — без ML,
поэтому каждую рекомендацию можно объяснить тремя буллетами (критерий приёмки).
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.supabase_auth import SupabaseUser, require_supabase_user, supabase_client_id
from app.db import get_db
from app.db import repo as db_repo
from app.db import supplier_repo as srepo
from app.services.personalization import (
    TenderInterest,
    confidence_label,
    next_digest_time,
    rank_tenders,
)

router = APIRouter(prefix="/tenders", tags=["tenders"])
profile_router = APIRouter(tags=["profile"])


async def _user(session: AsyncSession, auth_user: SupabaseUser):
    identity = supabase_client_id(auth_user)
    return await db_repo.get_or_create_user(session, web_client_id=identity)


def _interests(row) -> TenderInterest:
    return TenderInterest(
        categories=list(row.categories or []),
        regions=list(row.regions or []),
        keywords=list(row.keywords or []),
        min_budget_kzt=row.min_budget_kzt,
        max_budget_kzt=row.max_budget_kzt,
        quiz_completed=bool(row.quiz_completed),
    )


class InterestsRequest(BaseModel):
    """Онбординг-квиз (cold start) и уточнение интересов."""

    categories: list[str] | None = Field(default=None, max_length=20)
    regions: list[str] | None = Field(default=None, max_length=20)
    keywords: list[str] | None = Field(default=None, max_length=30)
    min_budget_kzt: float | None = Field(default=None, ge=0)
    max_budget_kzt: float | None = Field(default=None, ge=0)
    quiz_completed: bool | None = None


@profile_router.get("/profile/interests", tags=["profile"])
async def get_interests(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    row = await srepo.get_or_create_interests(session, user.id)
    await session.commit()
    return {
        "categories": list(row.categories or []),
        "regions": list(row.regions or []),
        "keywords": list(row.keywords or []),
        "min_budget_kzt": row.min_budget_kzt,
        "max_budget_kzt": row.max_budget_kzt,
        "quiz_completed": bool(row.quiz_completed),
    }


@profile_router.patch("/profile/interests", tags=["profile"])
async def update_interests(
    payload: InterestsRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    row = await srepo.update_interests(
        session, user.id, payload.model_dump(exclude_none=True)
    )
    await session.commit()
    return {
        "categories": list(row.categories or []),
        "regions": list(row.regions or []),
        "keywords": list(row.keywords or []),
        "min_budget_kzt": row.min_budget_kzt,
        "max_budget_kzt": row.max_budget_kzt,
        "quiz_completed": bool(row.quiz_completed),
    }


class TenderFeedbackRequest(BaseModel):
    lot_id: str = Field(..., min_length=1, max_length=64)
    verdict: str = Field(..., pattern="^(fits|not_fits)$")


@router.post("/feedback")
async def tender_feedback(
    payload: TenderFeedbackRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Кнопки «подходит / не подходит» — топливо для скоринга v2 (F8)."""
    user = await _user(session, auth_user)
    await srepo.record_tender_feedback(session, user.id, payload.lot_id, payload.verdict)
    stats = await srepo.feedback_stats(session, user.id)
    await session.commit()
    return {"ok": True, "verdict": payload.verdict, "stats": stats}


class DigestRequest(BaseModel):
    channels: list[str] | None = Field(default=None, max_length=5)
    daily_limit: int | None = Field(default=None, ge=1, le=50)
    hour_kz: int | None = Field(default=None, ge=0, le=23)
    enabled: bool | None = None


@profile_router.get("/digest/settings", tags=["profile"])
async def get_digest_settings(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    row = await srepo.get_or_create_digest_settings(session, user.id)
    await session.commit()
    return {
        "channels": list(row.channels or []),
        "daily_limit": row.daily_limit,
        "hour_kz": row.hour_kz,
        "enabled": bool(row.enabled),
        "next_send_at": next_digest_time(row.hour_kz).isoformat(),
    }


@profile_router.patch("/digest/settings", tags=["profile"])
async def update_digest_settings(
    payload: DigestRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Настроить каналы, дневной лимит и время дайджеста (анти-спам, НФТ)."""
    user = await _user(session, auth_user)
    row = await srepo.update_digest_settings(
        session, user.id, payload.model_dump(exclude_none=True)
    )
    await session.commit()
    return {
        "channels": list(row.channels or []),
        "daily_limit": row.daily_limit,
        "hour_kz": row.hour_kz,
        "enabled": bool(row.enabled),
        "next_send_at": next_digest_time(row.hour_kz).isoformat(),
    }


@router.get("/recommended")
async def recommended(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Персонализированная подборка тендеров с объяснением «почему».

    Считается по лотам, уже сохранённым в БД (то есть найденным ранее),
    поэтому не требует отдельного запроса к goszakup.
    """
    user = await _user(session, auth_user)
    interests_row = await srepo.get_or_create_interests(session, user.id)
    interest = _interests(interests_row)
    await session.commit()

    lots = await _recent_lots(session, limit=300)
    scored = rank_tenders(lots, interest, limit=10, min_score=10)

    if not scored:
        return {
            "items": [],
            "total": 0,
            "cold_start": not interest.quiz_completed,
            "message": (
                "Пока нет подходящих закупок. Заполните интересы в профиле или "
                "разместите первый поиск лотов — подборка появится автоматически."
            ),
        }

    return {
        "items": [
            {**t.to_dict(), "confidence": confidence_label(t.score)} for t in scored
        ],
        "total": len(scored),
        "cold_start": not interest.quiz_completed,
        "message": "",
    }


async def _recent_lots(session: AsyncSession, *, limit: int = 300) -> list[dict[str, Any]]:
    """Взять свежие лоты из локальной БД как кандидатов для подборки."""
    from sqlalchemy import select

    from app.db.models import Lot

    stmt = (
        select(Lot)
        .order_by(Lot.publish_date.desc().nullslast(), Lot.id.desc())
        .limit(max(1, min(1000, limit)))
    )
    rows = (await session.execute(stmt)).scalars().all()
    today = __import__("datetime").date.today()
    out: list[dict[str, Any]] = []
    for lot in rows:
        deadline = lot.deadline_date
        days_left = None
        if deadline is not None:
            try:
                days_left = (deadline.date() - today).days
            except AttributeError:
                days_left = None
        out.append(
            {
                "lot_id": lot.source_id or str(lot.id),
                "title": lot.title,
                "description": lot.description,
                "category": lot.category,
                "region": lot.region,
                "customer": lot.organizer or "",
                "amount_kzt": lot.amount_kzt,
                "deadline_date": lot.deadline_date.isoformat() if lot.deadline_date else None,
                "is_urgent": bool(days_left is not None and days_left <= 3),
                "created_at": lot.publish_date.isoformat() if lot.publish_date else None,
            }
        )
    return out