"""API очереди одобрений и исходящих действий (F3–F5, ТЗ §7).

Маршруты: /api/approvals/*, /api/outreach/*

Главный инвариант (проверяется тестом в критериях приёмки):
исходящее действие невозможно без approval со статусом ``approved``.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.supabase_auth import SupabaseUser, require_supabase_user, supabase_client_id
from app.db import get_db
from app.db import repo as db_repo
from app.db import supplier_repo as srepo
from app.services.outreach import OutreachNotAllowed, OutreachService, outreach_capabilities
from app.services.personalization import contacts_from_profile

router = APIRouter(tags=["approvals"])
outreach_router = APIRouter(prefix="/outreach", tags=["outreach"])

#: Соответствие внутренних ошибок политики на стабильные коды API.
_BLOCK_REASONS: dict[str, int] = {
    "APPROVAL_NOT_FOUND": 404,
    "APPROVAL_REQUIRED": 403,
    "APPROVAL_KIND_MISMATCH": 400,
    "SUPPLIER_BLOCKED": 403,
    "DRAFT_EMPTY": 400,
    "DRAFT_INVALID": 400,
    "DRAFT_HAS_OBLIGATION": 400,
    "DRAFT_HAS_STOP_WORD": 400,
    "MANUAL_MODE_BLOCKS_SENDING": 403,
    "MANUAL_MODE_BLOCKS_CALLING": 403,
    "DAILY_EMAIL_LIMIT_REACHED": 429,
    "DAILY_CALL_LIMIT_REACHED": 429,
    "DAILY_CALL_BUDGET_REACHED": 429,
    "OUTSIDE_WORKING_HOURS_KZ": 409,
    "RECIPIENT_EMAIL_MISSING": 409,
    "RECIPIENT_PHONE_MISSING": 409,
    "EMAIL_SEND_FAILED": 502,
    "CALL_FAILED": 502,
    "EMAIL_DISABLED_PENDING_LEGAL": 503,
    "CALL_DISABLED_PENDING_LEGAL": 503,
    "EMAIL_PROVIDER_NOT_CONFIGURED": 503,
    "CALL_PROVIDER_NOT_CONFIGURED": 503,
}


def _approval_payload(row, *, candidate=None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "draft_text": row.draft_text,
        "plan": row.plan_json or {},
        "decision_note": row.decision_note,
        "candidate_id": row.candidate_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }
    if candidate is not None:
        payload["supplier"] = candidate.supplier
        payload["lot_id"] = candidate.lot_id
        card = candidate.card_json or {}
        payload["recipient"] = {
            "email": card.get("email", ""),
            "phone": card.get("phone", ""),
        }
    return payload


async def _user(session: AsyncSession, auth_user: SupabaseUser):
    identity = supabase_client_id(auth_user)
    return await db_repo.get_or_create_user(session, web_client_id=identity)


class DecisionRequest(BaseModel):
    """Решение пользователя по заявке: одобрить или отклонить."""

    approval_id: int = Field(..., gt=0)
    decision: str = Field(..., pattern="^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=512)
    edited_text: str | None = Field(
        default=None, max_length=8000, description="Отредактированный пользователем текст"
    )


@router.post("/approvals", tags=["approvals"])
async def decide(
    payload: DecisionRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Одобрить или отклонить черновик письма / план звонка.

    Только ``approved`` открывает возможность исходящего действия.
    """
    user = await _user(session, auth_user)
    row = await srepo.decide_approval(
        session,
        user.id,
        payload.approval_id,
        decision=payload.decision,
        note=payload.note,
        edited_text=payload.edited_text,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="APPROVAL_NOT_FOUND")

    candidate = (
        await srepo.get_candidate(session, user.id, row.candidate_id)
        if row.candidate_id
        else None
    )
    await srepo.log_action(
        session,
        user_id=user.id,
        action="decision",
        lot_id=candidate.lot_id if candidate else None,
        target=candidate.supplier[:256] if candidate else None,
        detail_json={"approval_id": row.id, "kind": row.kind, "decision": payload.decision},
    )
    await session.commit()
    return _approval_payload(row, candidate=candidate)


@router.get("/approvals/pending", tags=["approvals"])
async def pending_approvals(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Все заявки, ожидающие решения пользователя."""
    user = await _user(session, auth_user)
    rows = await srepo.list_approvals(session, user.id, status="pending")
    out: list[dict[str, Any]] = []
    for row in rows:
        candidate = (
            await srepo.get_candidate(session, user.id, row.candidate_id)
            if row.candidate_id
            else None
        )
        out.append(_approval_payload(row, candidate=candidate))
    return {"items": out, "total": len(out)}


@router.get("/approvals", tags=["approvals"])
async def list_approvals(
    status: str | None = None,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)] = None,
    session: Annotated[AsyncSession, Depends(get_db)] = None,
) -> dict[str, Any]:
    """История решений по исходящим действиям."""
    if auth_user is None or session is None:  # pragma: no cover - защита
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    user = await _user(session, auth_user)
    rows = await srepo.list_approvals(session, user.id, status=status)
    return {
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


class SendEmailRequest(BaseModel):
    approval_id: int = Field(..., gt=0)
    subject: str = Field(..., min_length=1, max_length=200)


@outreach_router.get("/capabilities")
async def get_outreach_capabilities(
    _auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
) -> dict[str, Any]:
    """Tell the UI which real providers are configured; no simulated sends."""
    return outreach_capabilities()


@outreach_router.post("/email")
async def send_email(
    payload: SendEmailRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Отправить письмо по одобренной заявке. Без approval — 403."""
    user = await _user(session, auth_user)
    profile = await srepo.get_or_create_company_profile(session, user.id)
    service = OutreachService()
    try:
        result = await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=payload.approval_id,
            subject=payload.subject,
            contacts=contacts_from_profile(profile),
        )
    except OutreachNotAllowed as exc:
        await session.commit()
        raise HTTPException(
            status_code=_BLOCK_REASONS.get(str(exc), 403), detail=str(exc)
        ) from exc
    await session.commit()
    return {
        "job_id": result.job_id,
        "status": result.status,
        "mode": result.mode,
        "external_id": result.external_id,
    }


class CallRequest(BaseModel):
    approval_id: int = Field(..., gt=0)


@outreach_router.post("/call")
async def place_call(
    payload: CallRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Инициировать звонок по одобренному плану.

    Дополнительно блокируется вне рабочего времени Казахстана.
    """
    user = await _user(session, auth_user)
    service = OutreachService()
    try:
        result = await service.place_approved_call(
            session, user_id=user.id, approval_id=payload.approval_id
        )
    except OutreachNotAllowed as exc:
        await session.commit()
        raise HTTPException(
            status_code=_BLOCK_REASONS.get(str(exc), 403), detail=str(exc)
        ) from exc
    await session.commit()
    return {
        "job_id": result.job_id,
        "status": result.status,
        "mode": result.mode,
        "external_id": result.external_id,
    }


@outreach_router.get("/{job_id}")
async def get_job(
    job_id: int,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Статус задания и расшифровка звонка (если есть)."""
    user = await _user(session, auth_user)
    job = await srepo.get_outreach_job(session, user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "recipient": job.recipient,
        "price_outcome": job.price_outcome,
        "transcription": job.transcription or "",
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@outreach_router.get("/jobs/list")
async def list_jobs(
    kind: str | None = None,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)] = None,
    session: Annotated[AsyncSession, Depends(get_db)] = None,
) -> dict[str, Any]:
    if auth_user is None or session is None:  # pragma: no cover
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    user = await _user(session, auth_user)
    rows = await srepo.list_outreach_jobs(session, user.id, kind=kind)
    return {
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "price_outcome": r.price_outcome,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@outreach_router.get("/audit/costs")
async def audit_costs(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Расходы агента по типам — для контроля себестоимости (F10, НФТ)."""
    user = await _user(session, auth_user)
    summary = await srepo.cost_summary(session, user.id)
    summary["total_usd"] = round(sum(summary.values()), 6)
    return summary


@router.get("/audit", tags=["approvals"])
async def audit_log(
    limit: int = 50,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)] = None,
    session: Annotated[AsyncSession, Depends(get_db)] = None,
) -> dict[str, Any]:
    """Журнал действий агента: поиски, сверки, решения, письма, звонки (F10)."""
    if auth_user is None or session is None:  # pragma: no cover
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    user = await _user(session, auth_user)
    rows = await srepo.list_audit(session, user.id, limit=limit)
    return {
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "lot_id": r.lot_id,
                "target": r.target,
                "detail": r.detail_json or {},
                "costs": {
                    "llm": r.llm_cost_usd,
                    "tavily": r.tavily_cost_usd,
                    "browser": r.browser_cost_usd,
                    "call": r.call_cost_usd,
                },
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
