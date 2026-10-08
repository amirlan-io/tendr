"""Песочница агента поставщиков: прогон на реальных данных с полным следом.

Зачем
----
Продуктовые решения о фиче принимались на моках, а потом оказывались
неверными на живых данных: один позиционный товар вытеснял остальные,
а телефоны казахстанских площадок не распознавались. Нужна площадка,
где видно не только результат, но и что именно агент делал.

Что даёт песочница
------------------
* след: какие запросы пробовались, что вернул поиск, что сделала сверка;
* фильтры: регион, бюджет, только прямые поставщики, требовать контакты;
* персонализация: профиль компании влияет на запросы и на приоритет;
* стоимость: прозрачная оценка по числу вызовов (не банковский чек).

Ничего не отправляется наружу: агент только читает страницы. Любой вызов
исходящего контакта по-прежнему идёт через approval.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.supplier_agent import SupplierAgent, dedupe_requirements
from app.core.supabase_auth import SupabaseUser, require_supabase_user, supabase_client_id
from app.db import get_db
from app.db import repo as db_repo
from app.db import supplier_repo as srepo
from app.services.goszakup_parser import build_lot_url
from app.services.personalization import CompanyContext, build_company_block

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class SandboxRequest(BaseModel):
    """Запуск агента в песочнице."""

    lot_id: str = Field(..., min_length=1, max_length=64)
    # Требования можно задать вручную, иначе берутся из последнего анализа.
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    # Пробовать несколько формулировок запроса на каждый пункт.
    query_variants: int = Field(default=2, ge=1, le=5)
    # Сколько кандидатов вернуть.
    limit: int = Field(default=15, ge=1, le=20)
    # Фильтры
    regions: list[str] = Field(default_factory=list, max_length=10)
    min_price_kzt: float | None = Field(default=None, ge=0)
    max_price_kzt: float | None = Field(default=None, ge=0)
    budget_kzt: float | None = Field(default=None, ge=0)
    only_direct: bool = Field(default=False, description="Только сайты компаний, без маркетплейсов")
    only_with_price: bool = Field(default=False)
    only_with_contacts: bool = Field(default=False)
    # Использовать профиль компании для персонализации запросов.
    use_company_profile: bool = Field(default=True)
    enrich_browser: bool = Field(default=False, description="Читать страницы (медленно)")
    # Сколько страниц поставщиков прочитать. Больше — выше шанс найти
    # цену и телефон, но дольше и больше запросов к Jina.
    page_fetch_top_n: int = Field(default=10, ge=0, le=20)
    save_results: bool = Field(default=False, description="Сохранить шорт-лист в БД")


@router.post("/suppliers")
async def run_supplier_sandbox(
    payload: SandboxRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Прогнать агента и вернуть результат вместе со следом работы."""
    started = time.monotonic()
    identity = supabase_client_id(auth_user)
    user = await db_repo.get_or_create_user(session, web_client_id=identity)

    # Анализ нужен не только для требований: в нём лежат бюджет и регион
    # поставки. Раньше при ручных requirements анализ вообще не читался.
    analysis = await db_repo.get_analysis_by_lot(session, user.id, payload.lot_id)
    requirements = dedupe_requirements(payload.requirements[:25])
    if not requirements:
        requirements = dedupe_requirements(_requirements_from_analysis(analysis))
    if not requirements:
        raise HTTPException(
            status_code=400,
            detail="SANDBOX_REQUIREMENTS_MISSING",
        )
    # Бюджет лота обязателен: без него агент не может отсеять поставщиков
    # дороже закупки. Раньше сюда жёстко передавался None, и на лоте
    # «фильтры + регулятор, 48 000 тг» бюджет просто не учитывался.
    budget_kzt = payload.budget_kzt or _budget_from_analysis(analysis)
    lot_region = _region_from_analysis(analysis)

    # Персонализация: профиль компании подмешивается в контекст запросов.
    context_block = ""
    company_terms: list[str] = []
    if payload.use_company_profile:
        profile_row = await srepo.get_or_create_company_profile(session, user.id)
        context = CompanyContext(
            categories=list(profile_row.categories or []),
            regions=list(profile_row.regions or []),
            capabilities=str(profile_row.capabilities or ""),
            min_check_kzt=profile_row.min_check_kzt,
            budget_max_kzt=profile_row.budget_max_kzt,
        )
        context_block = build_company_block(context)
        # Категории профиля идут в запросы: без этого персонализация была
        # только текстом в trace, который ни на что не влиял.
        company_terms = [c for c in context.categories if c][:5]
        # Регионы профиля не превращаем в строгий фильтр поставщиков.
        # Компания из Астаны может участвовать в лоте Акмолинской области;
        # географию самого лота берём из анализа ниже.

    blocked = {row.supplier for row in await srepo.list_blocked(session, user.id)}

    agent = SupplierAgent()
    candidates, costs, meta = await agent.find_suppliers(
        requirements,
        budget_kzt=budget_kzt,
        blocked=blocked,
        enrich_browser=payload.enrich_browser,
        query_variants=payload.query_variants,
        page_fetch_top_n=payload.page_fetch_top_n,
        region_hint=payload.regions[0] if payload.regions else lot_region,
        company_terms=company_terms,
        # Сначала дешёвые фильтры и limit, затем дорогая LLM-сверка.
        perform_matching=False,
    )

    applied, filter_stats = _apply_filters(
        candidates,
        regions=payload.regions,
        min_price=payload.min_price_kzt,
        max_price=payload.max_price_kzt,
        only_direct=payload.only_direct,
        only_with_price=payload.only_with_price,
        only_with_contacts=payload.only_with_contacts,
        budget_kzt=budget_kzt,
    )
    applied = applied[: payload.limit]

    # Сверяем только тот шорт-лист, который реально увидит пользователь.
    # Раньше LLM обрабатывала все 20 карточек до фильтров и одинаковая
    # «стоимость» вводила в заблуждение.
    match_costs = await agent.match_requirements(applied, requirements)
    costs.merge(match_costs)
    agent.assess_budget(applied, requirements, budget_kzt)
    within_budget = []
    for candidate in applied:
        if budget_kzt and candidate.budget_status == "over_budget":
            filter_stats["dropped_budget"] += 1
            continue
        within_budget.append(candidate)
    applied = sorted(
        within_budget,
        key=lambda c: (-c.score, c.domain.lower(), c.url.lower()),
    )

    if payload.save_results and applied:
        await srepo.replace_candidates(
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
                for c in applied
            ],
        )
        await session.commit()

    return {
        "lot_id": payload.lot_id,
        "lot_url": build_lot_url(payload.lot_id),
        "requirements": [
            {
                "code": r.code,
                "title": r.title,
                # Описание содержит характеристики ТЗ: без них в запросы не
                # попадают «60,3 Мпа», «фланцевый», «80 мм».
                "description": r.description or None,
                "mandatory": r.is_mandatory,
            }
            for r in requirements
        ],
        "trace": {
            "queries": meta.get("queries", []),
            "direct_queries": meta.get("direct_queries", []),
            "planned_queries": meta.get("planned_queries", []),
            "search_call_limit": meta.get("search_call_limit", 0),
            "search_calls_attempted": meta.get("search_calls_attempted", 0),
            "resolution_gaps": meta.get("resolution_gaps", []),
            "found_before_filters": meta.get("candidates_count", 0),
            "blocked_filtered": meta.get("blocked_filtered", 0),
            # Сколько кандидатов отсеял каждый фильтр: раньше потеря
            # 20 → 1 была видна только как разница в total.
            "filtered_out": filter_stats,
            "pages_read": costs.page_fetch_count,
            "personalization": context_block,
            "filters_applied": {
                "regions": payload.regions,
                "price_range": [payload.min_price_kzt, payload.max_price_kzt],
                "only_direct": payload.only_direct,
                "only_with_price": payload.only_with_price,
                "only_with_contacts": payload.only_with_contacts,
                "budget_kzt": budget_kzt,
                "lot_region": lot_region,
            },
        },
        "costs": {
            "llm_usd": round(costs.llm_usd, 6),
            "tavily_usd": round(costs.tavily_usd, 6),
            "browser_usd": round(costs.browser_usd, 6),
            "total_usd": round(costs.llm_usd + costs.tavily_usd + costs.browser_usd, 6),
            "is_estimate": True,
            "llm_calls": costs.llm_calls,
            "tavily_calls": costs.tavily_calls,
            "tavily_attempts": costs.tavily_attempts,
            "browser_calls": costs.browser_calls,
        },
        "duration_sec": round(time.monotonic() - started, 1),
        "total": len(applied),
        "candidates": [_card(c) for c in applied],
    }


def _card(candidate) -> dict[str, Any]:
    card = candidate.to_card()
    match = candidate.to_match()
    return {
        "supplier": candidate.supplier,
        "domain": candidate.domain,
        "title": candidate.title,
        "url": candidate.url,
        "score": candidate.score,
        "domain_kind": candidate.domain_kind,
        "price_kzt": card["price_kzt"],
        "city": card["city"],
        "email": card["email"],
        "phone": card["phone"],
        "estimated_total_kzt": card["estimated_total_kzt"],
        "budget_status": card["budget_status"],
        "requirement_matches": match["requirement_matches"],
        "warnings": match["warnings"],
    }


def _apply_filters(
    candidates, *, regions, min_price, max_price, only_direct,
    only_with_price, only_with_contacts, budget_kzt=None,
) -> tuple[list, dict[str, int]]:
    """Фильтры применяются в коде, а не в промпте — их можно проверить тестом.

    Возвращает также статистику отбрасываний. Раньше она не считалась, и по
    следу (20 кандидатов → 1) было невозможно понять, какой именно фильтр
    вырезал почти всю выдачу.

    Регион: кандидат с НЕИЗВЕСТНЫМ городом не отбрасывается. «Не знаю
    город» — это не «не в том регионе», и раньше фильтр по «Астана»
    уничтожал 95 % выдачи, потому что город был заполнен у единиц.
    """
    out: list = []
    stats = {"dropped_region": 0, "dropped_price": 0, "dropped_direct": 0,
             "dropped_no_price": 0, "dropped_no_contacts": 0, "dropped_budget": 0,
             "unknown_city_kept": 0}
    for c in candidates:
        card = c.to_card()
        if regions:
            city = (card["city"] or "").strip()
            if not city:
                stats["unknown_city_kept"] += 1
            elif not any(r.lower() in city.lower() for r in regions):
                stats["dropped_region"] += 1
                continue
        if min_price is not None and (card["price_kzt"] is None or card["price_kzt"] < min_price):
            stats["dropped_price"] += 1
            continue
        if max_price is not None and (card["price_kzt"] is None or card["price_kzt"] > max_price):
            stats["dropped_price"] += 1
            continue
        if only_direct and c.domain_kind != "direct":
            stats["dropped_direct"] += 1
            continue
        if only_with_price and not card["price_kzt"]:
            stats["dropped_no_price"] += 1
            continue
        if only_with_contacts and not (card["email"] or card["phone"]):
            stats["dropped_no_contacts"] += 1
            continue
        if budget_kzt and getattr(c, "budget_status", "unknown") == "over_budget":
            stats["dropped_budget"] += 1
            continue
        out.append(c)
    return out, stats


def _budget_from_analysis(analysis) -> float | None:
    """Бюджет лота из сохранённого анализа.

    Без него агент не понимает цену позиции: на лоте «фильтры + регулятор,
    48 000 тг» поставщик с ценой 107 000 ₸ за штуку не подходит вовсе,
    но агент такого поставщика не отсеивал.
    """
    if analysis is None:
        return None
    for value in (getattr(analysis, "budget_kzt", None),):
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    result = analysis.result_json if isinstance(analysis.result_json, dict) else {}
    lot = result.get("lot") if isinstance(result.get("lot"), dict) else {}
    for key in ("budget_kzt", "amount_kzt", "estimated_budget_kzt"):
        value = lot.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _region_from_analysis(analysis) -> str:
    """Регион поставки лота, а не домашний регион профиля компании."""
    if analysis is None or not isinstance(analysis.result_json, dict):
        return ""
    lot = analysis.result_json.get("lot")
    if not isinstance(lot, dict):
        return ""
    for key in ("region", "delivery_region", "delivery_address"):
        value = str(lot.get(key) or "").strip()
        if value:
            return value[:160]
    return ""


def _requirements_from_analysis(analysis) -> list[dict[str, Any]]:
    """Пункты ТЗ из анализа. Documenter отдаёт name/value/is_critical."""
    if analysis is None or not isinstance(analysis.result_json, dict):
        return []
    lot = analysis.result_json.get("lot") or {}
    if not isinstance(lot, dict):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(lot.get("requirements") or [], start=1):
        if isinstance(item, str):
            out.append({"code": str(index), "title": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        out.append(
            {
                "code": str(item.get("code") or index),
                "title": title,
                "description": str(item.get("description") or item.get("value") or ""),
                "is_mandatory": bool(item.get("is_mandatory") or item.get("is_critical")),
            }
        )
    return out


# ── Персонализация ────────────────────────────────────────────────────


class InterestRequest(BaseModel):
    categories: list[str] | None = Field(default=None, max_length=20)
    regions: list[str] | None = Field(default=None, max_length=20)
    keywords: list[str] | None = Field(default=None, max_length=30)
    min_budget_kzt: float | None = Field(default=None, ge=0)
    max_budget_kzt: float | None = Field(default=None, ge=0)
    quiz_completed: bool | None = None


@router.post("/interests")
async def set_interests(
    payload: InterestRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Сохранить интересы — они влияют на подбор и песочницу."""
    user = await db_repo.get_or_create_user(
        session, web_client_id=supabase_client_id(auth_user)
    )
    row = await srepo.update_interests(session, user.id, payload.model_dump(exclude_none=True))
    await session.commit()
    return {
        "categories": list(row.categories or []),
        "regions": list(row.regions or []),
        "keywords": list(row.keywords or []),
        "quiz_completed": bool(row.quiz_completed),
    }


class ProfileRequest(BaseModel):
    categories: list[str] | None = Field(default=None, max_length=20)
    regions: list[str] | None = Field(default=None, max_length=20)
    capabilities: str | None = Field(default=None, max_length=4000)
    min_check_kzt: float | None = Field(default=None, ge=0)
    budget_max_kzt: float | None = Field(default=None, ge=0)
    work_email: str | None = Field(default=None, max_length=255)
    work_phone: str | None = Field(default=None, max_length=32)
    contact_name: str | None = Field(default=None, max_length=128)
    outreach_mode: Literal["manual", "review", "trusted"] | None = None


@router.post("/profile")
async def set_profile(
    payload: ProfileRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Профиль компании — из него собирается персонализация агента."""
    user = await db_repo.get_or_create_user(
        session, web_client_id=supabase_client_id(auth_user)
    )
    row = await srepo.update_company_profile(session, user.id, payload.model_dump(exclude_none=True))
    await session.commit()
    return {
        "categories": list(row.categories or []),
        "regions": list(row.regions or []),
        "capabilities": row.capabilities or "",
        "min_check_kzt": row.min_check_kzt,
        "budget_max_kzt": row.budget_max_kzt,
        "work_email": row.work_email or "",
        "work_phone": row.work_phone or "",
        "contact_name": row.contact_name or "",
        "outreach_mode": row.outreach_mode,
    }


@router.get("/profile")
async def get_profile(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    user = await db_repo.get_or_create_user(
        session, web_client_id=supabase_client_id(auth_user)
    )
    row = await srepo.get_or_create_company_profile(session, user.id)
    interests = await srepo.get_or_create_interests(session, user.id)
    await session.commit()
    return {
        "categories": list(row.categories or []),
        "regions": list(row.regions or []),
        "capabilities": row.capabilities or "",
        "min_check_kzt": row.min_check_kzt,
        "budget_max_kzt": row.budget_max_kzt,
        "work_email": row.work_email or "",
        "work_phone": row.work_phone or "",
        "contact_name": row.contact_name or "",
        "outreach_mode": row.outreach_mode,
        "interests": {
            "categories": list(interests.categories or []),
            "regions": list(interests.regions or []),
            "keywords": list(interests.keywords or []),
            "quiz_completed": bool(interests.quiz_completed),
        },
    }
