"""API поиска поставщиков и шорт-листа (F1–F3, ТЗ §7).

Маршруты: /api/suppliers/*
Авторизация — обязательна (require_supabase_user): агент работает с
коммерчески чувствительными данными конкретного пользователя.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.outreach_agent import OutreachAgent
from app.agents.supplier_agent import dedupe_requirements
from app.core.supabase_auth import SupabaseUser, require_supabase_user, supabase_client_id
from app.db import get_db
from app.db import repo as db_repo
from app.db import supplier_repo as srepo
from app.services.personalization import contacts_from_profile
from app.services.price_policy import decide_price_action

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

MAX_REQUIREMENTS = 25


async def _user(session: AsyncSession, auth_user: SupabaseUser) -> Any:
    identity = supabase_client_id(auth_user)
    return await db_repo.get_or_create_user(session, web_client_id=identity)


def _candidate_payload(row) -> dict[str, Any]:
    """Карточка + сверка. Объяснение по пунктам ТЗ идёт первым (F2)."""
    match = row.match_json or {}
    card = row.card_json or {}
    return {
        "id": row.id,
        "lot_id": row.lot_id,
        "supplier": row.supplier,
        "domain": row.domain,
        "title": row.title,
        "status": row.status,
        "score": row.score,
        "card": {
            "url": card.get("url", ""),
            "price_kzt": card.get("price_kzt"),
            "in_stock": card.get("in_stock"),
            "city": card.get("city", ""),
            "delivery_days": card.get("delivery_days"),
            "email": card.get("email", ""),
            "phone": card.get("phone", ""),
            "certificates": card.get("certificates", []),
            "warranty": card.get("warranty", ""),
            "sources": card.get("sources", {}),
            "is_middleman": card.get("is_middleman", False),
            # direct / aggregator / classifieds / unknown — UI показывает
            # прямых поставщиков отдельно от площадок-посредников.
            "domain_kind": card.get("domain_kind", "unknown"),
            "estimated_total_kzt": card.get("estimated_total_kzt"),
            "budget_status": card.get("budget_status", "unknown"),
        },
        "requirement_matches": match.get("requirement_matches", []),
        "warnings": match.get("warnings", []),
    }


class SearchRequest(BaseModel):
    """Запуск поиска поставщиков по лоту."""

    lot_id: str = Field(..., min_length=1, max_length=64)
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    budget_kzt: float | None = Field(default=None, ge=0)
    enrich_browser: bool = Field(
        default=True, description="Читать сайты поставщиков через Browser-Use (медленнее, дороже)"
    )


class SearchResponse(BaseModel):
    lot_id: str
    candidates: list[dict[str, Any]] = []
    queries: list[str] = []
    summary: str = ""
    blocked_filtered: int = 0
    costs_usd: dict[str, float] = {}


@router.post("/search", response_model=SearchResponse)
async def search_suppliers(
    payload: SearchRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    """Найти поставщиков по пунктам ТЗ и вернуть шорт-лист со сверкой."""
    user = await _user(session, auth_user)
    requirements = dedupe_requirements(payload.requirements[:MAX_REQUIREMENTS])
    if not requirements:
        raise HTTPException(status_code=400, detail="REQUIREMENTS_REQUIRED")

    blocked = {row.supplier for row in await srepo.list_blocked(session, user.id)}

    # Контекст должен работать и в основном поиске, не только в песочнице.
    analysis = await db_repo.get_analysis_by_lot(session, user.id, payload.lot_id)
    lot_data = (
        analysis.result_json.get("lot", {})
        if analysis is not None and isinstance(analysis.result_json, dict)
        else {}
    )
    if not isinstance(lot_data, dict):
        lot_data = {}
    budget_kzt = payload.budget_kzt or getattr(analysis, "budget_kzt", None)
    if not budget_kzt:
        budget_kzt = lot_data.get("budget_kzt") or lot_data.get("amount_kzt")
    region_hint = str(
        lot_data.get("region")
        or lot_data.get("delivery_region")
        or lot_data.get("delivery_address")
        or ""
    )[:160]
    profile = await srepo.get_or_create_company_profile(session, user.id)
    company_terms = [str(value) for value in (profile.categories or []) if value][:5]

    from app.agents.supplier_agent import SupplierAgent, has_mandatory_mismatch, has_supported_match

    agent = SupplierAgent()
    if not agent._tavily_client:
        raise HTTPException(status_code=503, detail="SEARCH_PROVIDER_NOT_CONFIGURED")
    candidates, costs, meta = await agent.find_suppliers(
        requirements,
        budget_kzt=float(budget_kzt) if isinstance(budget_kzt, (int, float)) else None,
        blocked=blocked,
        enrich_browser=payload.enrich_browser,
        region_hint=region_hint,
        company_terms=company_terms,
    )
    # Известная расчётная стоимость выше бюджета не должна попадать в
    # рабочий шорт-лист. Кандидаты без цены остаются с честным «нет данных».
    candidates = [c for c in candidates if c.budget_status != "over_budget"
                  and not has_mandatory_mismatch(c, requirements)
                  and has_supported_match(c, requirements)]

    rows = await srepo.replace_candidates(
        session,
        user.id,
        payload.lot_id,
        [
            {
                "supplier": c.supplier,
                "domain": c.domain,
                "title": c.title,
                "score": c.score,
                "card": c.to_card(),
                "match": c.to_match(),
            }
            for c in candidates
        ],
    )
    await session.commit()

    await srepo.log_action(
        session,
        user_id=user.id,
        action="search",
        lot_id=payload.lot_id,
        detail_json={
            "candidates": len(rows),
            "queries": meta.get("queries", []),
            "blocked_filtered": meta.get("blocked_filtered", 0),
        },
        llm_cost_usd=costs.llm_usd,
        tavily_cost_usd=costs.tavily_usd,
        browser_cost_usd=costs.browser_usd,
    )
    await session.commit()

    return SearchResponse(
        lot_id=payload.lot_id,
        candidates=[_candidate_payload(r) for r in rows],
        queries=meta.get("queries", []),
        summary=f"Найдено поставщиков: {len(rows)}",
        blocked_filtered=meta.get("blocked_filtered", 0),
        costs_usd={
            "llm": costs.llm_usd,
            "tavily": costs.tavily_usd,
            "browser": costs.browser_usd,
        },
    )


@router.get("/shortlist")
async def get_shortlist(
    lot_id: str,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Шорт-лист по лоту (без повторного поиска)."""
    user = await _user(session, auth_user)
    rows = await srepo.get_shortlist(session, user.id, lot_id)
    return {"lot_id": lot_id, "candidates": [_candidate_payload(r) for r in rows]}


@router.get("/requirements")
async def get_lot_requirements(
    lot_id: str,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Требования ТЗ по последнему анализу лота — вход для агента.

    Отдельный ручкой, а не клиентским состоянием: пользователь может
    открыть страницу поиска поставщиков напрямую или после перезагрузки.
    Если анализа не было — честный пустой ответ с подсказкой, а не
    выдуманные требования.
    """
    user = await _user(session, auth_user)
    analysis = await db_repo.get_analysis_by_lot(session, user.id, lot_id)
    requirements = _requirements_from_analysis(analysis)
    lot = (analysis.result_json or {}).get("lot", {}) if analysis else {}
    return {
        "lot_id": lot_id,
        "title": (lot.get("title") or (analysis.title if analysis else "")) or "",
        "customer": (lot.get("customer") or (analysis.customer if analysis else "")) or "",
        "budget_kzt": analysis.budget_kzt if analysis else None,
        "requirements": requirements,
        "has_analysis": bool(requirements),
        "message": (
            ""
            if requirements
            else "Для этого лота ещё нет разбора ТЗ. Запустите AI-анализ — тогда агент найдёт поставщиков именно по вашим требованиям."
        ),
    }


class FeedbackRequest(BaseModel):
    candidate_id: int = Field(..., gt=0)
    verdict: str = Field(..., pattern="^(fits|not_fits)$")


@router.post("/feedback")
async def supplier_feedback(
    payload: FeedbackRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Одобрить или отклонить поставщика — топливо для будущего скоринга."""
    user = await _user(session, auth_user)
    candidate = await srepo.get_candidate(session, user.id, payload.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="CANDIDATE_NOT_FOUND")

    status = "approved" if payload.verdict == "fits" else "rejected"
    await srepo.set_candidate_status(session, user.id, payload.candidate_id, status)
    await srepo.log_action(
        session,
        user_id=user.id,
        action="decision",
        lot_id=candidate.lot_id,
        target=candidate.supplier[:256],
        detail_json={"verdict": payload.verdict},
    )
    await session.commit()
    return {"ok": True, "candidate_id": payload.candidate_id, "status": status}


class DraftRequest(BaseModel):
    """Запрос на подготовку черновика письма или плана звонка."""

    candidate_id: int = Field(..., gt=0)
    kind: str = Field(..., pattern="^(email|call)$")


def _requirement_lines(requirements: list[dict[str, Any]]) -> list[str]:
    """Человекочитаемые строки для промпта: «название — описание»."""
    lines: list[str] = []
    for req in requirements[:12]:
        title = str(req.get("title") or "").strip()
        if not title:
            continue
        description = str(req.get("description") or "").strip()
        mark = " [обязательный]" if req.get("is_mandatory") else ""
        lines.append(f"- {title}{mark}" + (f": {description}" if description else ""))
    return lines


@router.post("/draft")
async def create_draft(
    payload: DraftRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Подготовить черновик письма или план звонка (ничего не отправляет)."""
    user = await _user(session, auth_user)
    candidate = await srepo.get_candidate(session, user.id, payload.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="CANDIDATE_NOT_FOUND")

    analysis = await db_repo.get_analysis_by_lot(session, user.id, candidate.lot_id)
    requirements = _requirements_from_analysis(analysis)

    profile = await srepo.get_or_create_company_profile(session, user.id)
    contacts = contacts_from_profile(profile)

    # Политика цены решается ДО генерации текста (F6).
    price = (candidate.card_json or {}).get("price_kzt")
    policy = await srepo.get_or_create_price_policy(session, user.id)
    action, deviation = decide_price_action(
        float(price) if price is not None else 0.0,
        float(analysis.budget_kzt) if analysis and analysis.budget_kzt else 0.0,
        tolerance_pct=float(policy.tolerance_pct),
        counter_limit_pct=float(policy.counter_limit_pct),
        counter_used=candidate.status == "counter_used",
    )

    agent = OutreachAgent()
    lot_title = (analysis.title if analysis and analysis.title else candidate.title) or candidate.title
    requirement_lines = _requirement_lines(requirements)
    if payload.kind == "email":
        draft = await agent.draft_email(
            supplier_name=candidate.supplier,
            lot_title=lot_title,
            requirements=requirement_lines,
            contacts=contacts,
            known_price_kzt=analysis.budget_kzt if analysis else None,
            price_action=action,
            counter_script=policy.counter_script,
        )
        approval = await srepo.create_approval(
            session,
            user_id=user.id,
            candidate_id=candidate.id,
            kind="email",
            draft_text=str(draft.get("body") or ""),
            plan_json={"subject": draft.get("subject"), "price_action": action.value},
        )
    else:
        plan = await agent.draft_call_plan(
            supplier_name=candidate.supplier,
            lot_title=lot_title,
            requirements=requirement_lines,
            contacts=contacts,
            price_action=action,
            counter_script=policy.counter_script,
        )
        approval = await srepo.create_approval(
            session,
            user_id=user.id,
            candidate_id=candidate.id,
            kind="call",
            draft_text=str(plan.get("introduction") or ""),
            plan_json=plan,
        )
        draft = plan

    await srepo.log_action(
        session,
        user_id=user.id,
        action="draft",
        lot_id=candidate.lot_id,
        target=candidate.supplier[:256],
        detail_json={"kind": payload.kind, "price_action": action.value, "deviation_pct": deviation},
        llm_cost_usd=0.0005,
    )
    await session.commit()

    return {
        "approval_id": approval.id,
        "kind": payload.kind,
        "status": approval.status,
        "price_action": action.value,
        "draft": draft,
    }


class PricePolicyRequest(BaseModel):
    tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    counter_limit_pct: float | None = Field(default=None, ge=0, le=100)
    counter_script: str | None = Field(default=None, max_length=2000)


@router.get("/price-policy")
async def get_price_policy(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    policy = await srepo.get_or_create_price_policy(session, user.id)
    await session.commit()
    return {
        "tolerance_pct": policy.tolerance_pct,
        "counter_limit_pct": policy.counter_limit_pct,
        "counter_script": policy.counter_script or "",
    }


@router.patch("/price-policy")
async def update_price_policy(
    payload: PricePolicyRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Настроить допуск X% и предел Y% для переговоров о цене (F6)."""
    user = await _user(session, auth_user)
    policy = await srepo.update_price_policy(
        session,
        user.id,
        payload.model_dump(exclude_none=True),
    )
    await session.commit()
    return {
        "tolerance_pct": policy.tolerance_pct,
        "counter_limit_pct": policy.counter_limit_pct,
        "counter_script": policy.counter_script or "",
    }


class BlocklistItem(BaseModel):
    supplier: str = Field(..., min_length=1, max_length=256)
    allow: bool = Field(default=False, description="True — белый список, False — стоп-лист")
    domain: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=512)


@router.get("/lists")
async def get_lists(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Белый и стоп-листы поставщиков."""
    user = await _user(session, auth_user)
    allowed = await srepo.list_allowed(session, user.id)
    blocked = await srepo.list_blocked(session, user.id)
    return {
        "allowlist": [{"supplier": r.supplier, "domain": r.domain, "note": r.note} for r in allowed],
        "blocklist": [{"supplier": r.supplier, "domain": r.domain, "reason": r.reason} for r in blocked],
    }


@router.post("/lists")
async def add_to_lists(
    payload: BlocklistItem,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    await srepo.add_to_list(
        session,
        user.id,
        payload.supplier,
        allow=payload.allow,
        domain=payload.domain,
        reason=payload.reason,
    )
    await session.commit()
    return {"ok": True, "supplier": payload.supplier, "allow": payload.allow}


@router.delete("/lists")
async def remove_from_lists(
    supplier: str,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    allow: bool = False,
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    removed = await srepo.remove_from_list(session, user.id, supplier, allow=allow)
    await session.commit()
    return {"ok": True, "removed": removed}


class CompanyProfileRequest(BaseModel):
    categories: list[str] | None = Field(default=None, max_length=20)
    regions: list[str] | None = Field(default=None, max_length=20)
    capabilities: str | None = Field(default=None, max_length=4000)
    min_check_kzt: float | None = Field(default=None, ge=0)
    budget_max_kzt: float | None = Field(default=None, ge=0)
    work_email: str | None = Field(default=None, max_length=255)
    work_phone: str | None = Field(default=None, max_length=32)
    contact_name: str | None = Field(default=None, max_length=128)
    outreach_mode: str | None = Field(default=None, pattern="^(manual|review|trusted)$")


@router.get("/profile")
async def get_company_profile(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await _user(session, auth_user)
    profile = await srepo.get_or_create_company_profile(session, user.id)
    await session.commit()
    return _company_profile_payload(profile)


@router.patch("/profile")
async def update_company_profile(
    payload: CompanyProfileRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Профиль компании: категории, регионы, мощности, рабочие контакты (F7)."""
    user = await _user(session, auth_user)
    profile = await srepo.update_company_profile(
        session, user.id, payload.model_dump(exclude_unset=True)
    )
    if user.company_name is None and profile.contact_name:
        user.company_name = user.company_name or profile.contact_name
    await session.commit()
    return _company_profile_payload(profile)


def _company_profile_payload(profile) -> dict[str, Any]:
    return {
        "categories": list(profile.categories or []),
        "regions": list(profile.regions or []),
        "capabilities": profile.capabilities or "",
        "min_check_kzt": profile.min_check_kzt,
        "budget_max_kzt": profile.budget_max_kzt,
        "work_email": profile.work_email or "",
        "work_phone": profile.work_phone or "",
        "contact_name": profile.contact_name or "",
        "outreach_mode": profile.outreach_mode,
    }


def _requirements_from_analysis(analysis) -> list[dict[str, Any]]:
    """Достать пункты ТЗ из сохранённого результата анализа.

    Documenter отдаёт ``name`` / ``value`` / ``is_critical``, а не
    ``title`` / ``description`` / ``is_mandatory`` — учитываем оба варианта,
    иначе в агент уйдут пустые требования.
    """
    if analysis is None or not isinstance(analysis.result_json, dict):
        return []
    lot = analysis.result_json.get("lot") or {}
    if not isinstance(lot, dict):
        return []
    requirements = lot.get("requirements") or []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(requirements[:12], start=1):
        if isinstance(item, str):
            title = item.strip()
            description = ""
            critical = False
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or "").strip()
            description = str(
                item.get("description") or item.get("value") or ""
            ).strip()
            critical = bool(item.get("is_mandatory") or item.get("is_critical"))
        else:
            continue
        if not title:
            continue
        out.append(
            {
                "code": str(item.get("code") or index) if isinstance(item, dict) else str(index),
                "title": title[:300],
                "description": description[:1000],
                "is_mandatory": critical,
            }
        )
    return out
