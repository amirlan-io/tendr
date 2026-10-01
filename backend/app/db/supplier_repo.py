"""Репозиторий Supplier Agent: кандидаты, approval, outreach, персонализация, аудит.

Все функции работают на существующей `users`-идентичности (web_client_id),
поэтому авторизация остаётся сквозной: без валидного client_id / Supabase-токена
данные недоступны.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentAuditLog,
    ApprovalQueue,
    CompanyProfile,
    DigestSetting,
    OutreachJob,
    PricePolicy,
    SupplierAllowlist,
    SupplierBlocklist,
    SupplierCandidate,
    TenderFeedback,
    User,
    UserInterest,
)

# ── Компания / профиль (F7) ────────────────────────────────────────────


async def get_or_create_company_profile(session: AsyncSession, user_id: int) -> CompanyProfile:
    stmt = select(CompanyProfile).where(CompanyProfile.user_id == user_id)
    profile = (await session.execute(stmt)).scalar_one_or_none()
    if profile is not None:
        return profile
    profile = CompanyProfile(user_id=user_id, categories=[], regions=[], outreach_mode="review")
    session.add(profile)
    await session.flush()
    return profile


async def update_company_profile(
    session: AsyncSession, user_id: int, payload: dict[str, Any]
) -> CompanyProfile:
    profile = await get_or_create_company_profile(session, user_id)
    for field in (
        "categories",
        "regions",
        "budget_min_kzt",
        "budget_max_kzt",
        "min_check_kzt",
        "capabilities",
        "work_email",
        "work_phone",
        "contact_name",
        "outreach_mode",
    ):
        if field in payload:
            setattr(profile, field, payload[field])
    await session.flush()
    return profile


# ── Списки поставщиков (F7) ────────────────────────────────────────────


async def is_blocked(session: AsyncSession, user_id: int, supplier: str) -> bool:
    stmt = select(func.count(SupplierBlocklist.id)).where(
        and_(SupplierBlocklist.user_id == user_id, SupplierBlocklist.supplier == supplier)
    )
    return int((await session.execute(stmt)).scalar() or 0) > 0


async def is_allowed(session: AsyncSession, user_id: int, supplier: str) -> bool:
    stmt = select(func.count(SupplierAllowlist.id)).where(
        and_(SupplierAllowlist.user_id == user_id, SupplierAllowlist.supplier == supplier)
    )
    return int((await session.execute(stmt)).scalar() or 0) > 0


async def list_blocked(session: AsyncSession, user_id: int) -> list[SupplierBlocklist]:
    stmt = select(SupplierBlocklist).where(SupplierBlocklist.user_id == user_id)
    return list((await session.execute(stmt)).scalars().all())


async def list_allowed(session: AsyncSession, user_id: int) -> list[SupplierAllowlist]:
    stmt = select(SupplierAllowlist).where(SupplierAllowlist.user_id == user_id)
    return list((await session.execute(stmt)).scalars().all())


async def add_to_list(
    session: AsyncSession,
    user_id: int,
    supplier: str,
    *,
    allow: bool,
    domain: str | None = None,
    reason: str | None = None,
) -> None:
    table = SupplierAllowlist if allow else SupplierBlocklist
    model = SupplierAllowlist if allow else SupplierBlocklist
    existing = await session.execute(
        select(model).where(and_(model.user_id == user_id, model.supplier == supplier))
    )
    row = existing.scalar_one_or_none()
    if row is None:
        kwargs: dict[str, Any] = {"user_id": user_id, "supplier": supplier, "domain": domain}
        if allow:
            kwargs["note"] = reason
        else:
            kwargs["reason"] = reason
        session.add(table(**kwargs))
    await session.flush()


async def remove_from_list(
    session: AsyncSession, user_id: int, supplier: str, *, allow: bool
) -> int:
    model = SupplierAllowlist if allow else SupplierBlocklist
    rows = await session.execute(
        select(model).where(and_(model.user_id == user_id, model.supplier == supplier))
    )
    deleted = 0
    for row in rows.scalars().all():
        await session.delete(row)
        deleted += 1
    await session.flush()
    return deleted


# ── Кандидаты-поставщики (F1–F3) ───────────────────────────────────────


async def replace_candidates(
    session: AsyncSession,
    user_id: int,
    lot_id: str,
    candidates: Sequence[dict[str, Any]],
) -> list[SupplierCandidate]:
    """Перезаписать шорт-лист для лота (idempotent: повторный поиск заменяет)."""
    existing = await session.execute(
        select(SupplierCandidate).where(
            and_(SupplierCandidate.user_id == user_id, SupplierCandidate.lot_id == lot_id)
        )
    )
    for row in existing.scalars().all():
        await session.delete(row)
    await session.flush()

    created: list[SupplierCandidate] = []
    for item in candidates:
        row = SupplierCandidate(
            user_id=user_id,
            lot_id=lot_id,
            supplier=str(item.get("supplier") or "")[:256],
            domain=(item.get("domain") or None),
            title=str(item.get("title") or "")[:512],
            card_json=item.get("card") or {},
            match_json=item.get("match") or {},
            score=int(item.get("score") or 0),
            status="pending",
        )
        session.add(row)
        created.append(row)
    await session.flush()
    return created


async def get_shortlist(
    session: AsyncSession, user_id: int, lot_id: str
) -> list[SupplierCandidate]:
    stmt = (
        select(SupplierCandidate)
        .where(and_(SupplierCandidate.user_id == user_id, SupplierCandidate.lot_id == lot_id))
        .order_by(SupplierCandidate.score.desc(), SupplierCandidate.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_candidate(session: AsyncSession, user_id: int, candidate_id: int) -> SupplierCandidate | None:
    stmt = select(SupplierCandidate).where(
        and_(SupplierCandidate.id == candidate_id, SupplierCandidate.user_id == user_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_candidate_status(
    session: AsyncSession, user_id: int, candidate_id: int, status: str
) -> SupplierCandidate | None:
    candidate = await get_candidate(session, user_id, candidate_id)
    if candidate is None:
        return None
    candidate.status = status
    await session.flush()
    return candidate


# ── Approval queue (F3–F6) ─────────────────────────────────────────────


async def create_approval(
    session: AsyncSession,
    *,
    user_id: int,
    candidate_id: int | None,
    kind: str,
    draft_text: str = "",
    plan_json: dict[str, Any] | None = None,
) -> ApprovalQueue:
    row = ApprovalQueue(
        user_id=user_id,
        candidate_id=candidate_id,
        kind=kind,
        draft_text=draft_text or "",
        plan_json=plan_json or {},
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row


async def get_approval(session: AsyncSession, user_id: int, approval_id: int) -> ApprovalQueue | None:
    stmt = select(ApprovalQueue).where(
        and_(ApprovalQueue.id == approval_id, ApprovalQueue.user_id == user_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_approvals(
    session: AsyncSession, user_id: int, *, status: str | None = None
) -> list[ApprovalQueue]:
    stmt = select(ApprovalQueue).where(ApprovalQueue.user_id == user_id)
    if status:
        stmt = stmt.where(ApprovalQueue.status == status)
    stmt = stmt.order_by(ApprovalQueue.created_at.desc(), ApprovalQueue.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def decide_approval(
    session: AsyncSession,
    user_id: int,
    approval_id: int,
    *,
    decision: str,
    note: str | None = None,
    edited_text: str | None = None,
) -> ApprovalQueue | None:
    """Зафиксировать решение пользователя: approved / rejected.

    Это единственная точка, которая может открыть исходящий контакт.
    """
    row = await get_approval(session, user_id, approval_id)
    if row is None:
        return None
    if row.status != "pending":
        # Решение по уже решённой заявке не меняем — аудит должен быть честным.
        return row
    row.status = decision
    row.decision_note = note
    row.decided_at = datetime.now(UTC).replace(tzinfo=None)
    if edited_text is not None:
        row.draft_text = edited_text
    await session.flush()
    return row


async def pending_approval_exists(session: AsyncSession, approval_id: int) -> bool:
    """Есть ли активное одобрение для задания (защита от повторной отправки)."""
    stmt = select(ApprovalQueue).where(
        and_(ApprovalQueue.id == approval_id, ApprovalQueue.status == "approved")
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


# ── Outreach jobs (F4–F5) ──────────────────────────────────────────────


async def create_outreach_job(
    session: AsyncSession,
    *,
    user_id: int,
    approval_id: int,
    kind: str,
    recipient: str,
    status: str = "queued",
    cost_usd: float = 0.0,
    external_id: str | None = None,
) -> OutreachJob:
    row = OutreachJob(
        user_id=user_id,
        approval_id=approval_id,
        kind=kind,
        recipient=recipient[:256],
        status=status,
        cost_usd=cost_usd,
        external_id=external_id,
    )
    session.add(row)
    await session.flush()
    return row


async def get_outreach_job(session: AsyncSession, user_id: int, job_id: int) -> OutreachJob | None:
    stmt = select(OutreachJob).where(
        and_(OutreachJob.id == job_id, OutreachJob.user_id == user_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_outreach_jobs(session: AsyncSession, user_id: int, *, kind: str | None = None) -> list[OutreachJob]:
    stmt = select(OutreachJob).where(OutreachJob.user_id == user_id)
    if kind:
        stmt = stmt.where(OutreachJob.kind == kind)
    stmt = stmt.order_by(OutreachJob.created_at.desc(), OutreachJob.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def count_jobs_today(session: AsyncSession, user_id: int, kind: str, *, since: datetime) -> int:
    stmt = select(func.count(OutreachJob.id)).where(
        and_(
            OutreachJob.user_id == user_id,
            OutreachJob.kind == kind,
            OutreachJob.created_at >= since,
        )
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def sum_call_cost_since(session: AsyncSession, user_id: int, *, since: datetime) -> float:
    stmt = select(func.coalesce(func.sum(OutreachJob.cost_usd), 0.0)).where(
        and_(
            OutreachJob.user_id == user_id,
            OutreachJob.kind == "call",
            OutreachJob.created_at >= since,
        )
    )
    return float((await session.execute(stmt)).scalar() or 0.0)


# ── Политика цен (F6) ──────────────────────────────────────────────────


async def get_or_create_price_policy(session: AsyncSession, user_id: int) -> PricePolicy:
    stmt = select(PricePolicy).where(PricePolicy.user_id == user_id)
    policy = (await session.execute(stmt)).scalar_one_or_none()
    if policy is not None:
        return policy
    from app.services.price_policy import default_counter_limit_pct, default_tolerance_pct

    policy = PricePolicy(
        user_id=user_id,
        tolerance_pct=default_tolerance_pct(),
        counter_limit_pct=default_counter_limit_pct(),
    )
    session.add(policy)
    await session.flush()
    return policy


async def update_price_policy(
    session: AsyncSession, user_id: int, payload: dict[str, Any]
) -> PricePolicy:
    from app.services.price_policy import normalize_pct

    policy = await get_or_create_price_policy(session, user_id)
    if "tolerance_pct" in payload:
        policy.tolerance_pct = normalize_pct(
            payload["tolerance_pct"], default=float(policy.tolerance_pct)
        )
    if "counter_limit_pct" in payload:
        policy.counter_limit_pct = max(
            normalize_pct(
                payload["counter_limit_pct"], default=float(policy.counter_limit_pct)
            ),
            float(policy.tolerance_pct),
        )
    if "counter_script" in payload:
        policy.counter_script = payload["counter_script"]
    await session.flush()
    return policy


# ── Интересы и обратная связь (F8) ─────────────────────────────────────


async def get_or_create_interests(session: AsyncSession, user_id: int) -> UserInterest:
    stmt = select(UserInterest).where(UserInterest.user_id == user_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row
    row = UserInterest(
        user_id=user_id, categories=[], regions=[], keywords=[], quiz_completed=False
    )
    session.add(row)
    await session.flush()
    return row


async def update_interests(session: AsyncSession, user_id: int, payload: dict[str, Any]) -> UserInterest:
    row = await get_or_create_interests(session, user_id)
    for field in (
        "categories",
        "regions",
        "keywords",
        "min_budget_kzt",
        "max_budget_kzt",
        "quiz_completed",
    ):
        if field in payload:
            setattr(row, field, payload[field])
    await session.flush()
    return row


async def record_tender_feedback(
    session: AsyncSession, user_id: int, lot_id: str, verdict: str
) -> TenderFeedback:
    row = TenderFeedback(user_id=user_id, lot_id=lot_id, verdict=verdict)
    session.add(row)
    await session.flush()
    return row


async def feedback_stats(session: AsyncSession, user_id: int) -> dict[str, int]:
    stmt = (
        select(TenderFeedback.verdict, func.count(TenderFeedback.id))
        .where(TenderFeedback.user_id == user_id)
        .group_by(TenderFeedback.verdict)
    )
    rows = (await session.execute(stmt)).all()
    return {str(verdict): int(count) for verdict, count in rows}


# ── Дайджест (F8) ──────────────────────────────────────────────────────


async def get_or_create_digest_settings(session: AsyncSession, user_id: int) -> DigestSetting:
    stmt = select(DigestSetting).where(DigestSetting.user_id == user_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row
    row = DigestSetting(user_id=user_id, channels=["telegram"], daily_limit=5, hour_kz=9, enabled=True)
    session.add(row)
    await session.flush()
    return row


async def update_digest_settings(
    session: AsyncSession, user_id: int, payload: dict[str, Any]
) -> DigestSetting:
    row = await get_or_create_digest_settings(session, user_id)
    if "channels" in payload:
        row.channels = payload["channels"]
    if "daily_limit" in payload:
        row.daily_limit = max(1, min(50, int(payload["daily_limit"])))
    if "hour_kz" in payload:
        row.hour_kz = max(0, min(23, int(payload["hour_kz"])))
    if "enabled" in payload:
        row.enabled = bool(payload["enabled"])
    await session.flush()
    return row


# ── Аудит и расходы (F10) ──────────────────────────────────────────────


async def log_action(
    session: AsyncSession,
    *,
    user_id: int,
    action: str,
    lot_id: str | None = None,
    target: str | None = None,
    detail_json: dict[str, Any] | None = None,
    llm_cost_usd: float = 0.0,
    tavily_cost_usd: float = 0.0,
    browser_cost_usd: float = 0.0,
    call_cost_usd: float = 0.0,
) -> AgentAuditLog:
    """Записать действие агента и его стоимость.

    В detail_json нельзя класть секреты и контакты третьих лиц — только
    технические детали для наблюдаемости.
    """
    row = AgentAuditLog(
        user_id=user_id,
        action=action,
        lot_id=lot_id,
        target=(target or None),
        detail_json=detail_json or {},
        llm_cost_usd=llm_cost_usd,
        tavily_cost_usd=tavily_cost_usd,
        browser_cost_usd=browser_cost_usd,
        call_cost_usd=call_cost_usd,
    )
    session.add(row)
    await session.flush()
    return row


async def cost_summary(session: AsyncSession, user_id: int) -> dict[str, float]:
    stmt = select(
        func.coalesce(func.sum(AgentAuditLog.llm_cost_usd), 0.0),
        func.coalesce(func.sum(AgentAuditLog.tavily_cost_usd), 0.0),
        func.coalesce(func.sum(AgentAuditLog.browser_cost_usd), 0.0),
        func.coalesce(func.sum(AgentAuditLog.call_cost_usd), 0.0),
    ).where(AgentAuditLog.user_id == user_id)
    row = (await session.execute(stmt)).one()
    return {
        "llm_usd": float(row[0] or 0.0),
        "tavily_usd": float(row[1] or 0.0),
        "browser_usd": float(row[2] or 0.0),
        "call_usd": float(row[3] or 0.0),
    }


async def list_audit(
    session: AsyncSession, user_id: int, *, limit: int = 50
) -> list[AgentAuditLog]:
    stmt = (
        select(AgentAuditLog)
        .where(AgentAuditLog.user_id == user_id)
        .order_by(AgentAuditLog.created_at.desc(), AgentAuditLog.id.desc())
        .limit(max(1, min(200, limit)))
    )
    return list((await session.execute(stmt)).scalars().all())


async def user_row(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)