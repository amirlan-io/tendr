"""Admin API: статистика для дашборда пилота."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import require_admin_key
from app.core.config import get_settings
from app.db import get_db
from app.db.models import Analysis, User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def stats(
    _admin: None = Depends(require_admin_key),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Сводная статистика для дашборда."""
    # Всего юзеров
    total_users = (await session.execute(select(func.count(User.id)))).scalar_one() or 0
    # Пилотные
    pilot_users = (
        await session.execute(select(func.count(User.id)).where(User.is_pilot == True))  # noqa: E712
    ).scalar_one() or 0
    # Подписанные
    sub_users = (
        await session.execute(select(func.count(User.id)).where(User.is_subscribed == True))  # noqa: E712
    ).scalar_one() or 0
    # Всего анализов
    total_analyses = (await session.execute(select(func.count(Analysis.id)))).scalar_one() or 0
    # Неполные (incomplete)
    incomplete = (
        await session.execute(
            select(func.count(Analysis.id)).where(Analysis.incomplete == True)  # noqa: E712
        )
    ).scalar_one() or 0
    # С жалобами
    with_complaint = (
        await session.execute(
            select(func.count(Analysis.id)).where(Analysis.overall_risk == "high")
        )
    ).scalar_one() or 0
    # За последние 7 дней
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_analyses = (
        await session.execute(
            select(func.count(Analysis.id)).where(Analysis.created_at >= week_ago)
        )
    ).scalar_one() or 0
    # За последние 24 часа
    day_ago = datetime.utcnow() - timedelta(days=1)
    day_analyses = (
        await session.execute(select(func.count(Analysis.id)).where(Analysis.created_at >= day_ago))
    ).scalar_one() or 0
    # Распределение по риску
    risk_dist = {}
    for r in ("low", "medium", "high", "needs_review"):
        cnt = (
            await session.execute(select(func.count(Analysis.id)).where(Analysis.overall_risk == r))
        ).scalar_one() or 0
        risk_dist[r] = cnt
    # Среднее требований
    avg_req = (await session.execute(select(func.avg(Analysis.n_requirements)))).scalar_one() or 0
    # Топ-5 заказчиков
    top_customers_q = (
        select(
            Analysis.customer,
            func.count(Analysis.id).label("cnt"),
        )
        .where(Analysis.customer != "")
        .where(Analysis.customer != "(не указан)")
        .where(Analysis.customer != "(лот не найден)")
        .group_by(Analysis.customer)
        .order_by(func.count(Analysis.id).desc())
        .limit(5)
    )
    top_customers = [
        {"customer": row[0], "count": row[1]}
        for row in (await session.execute(top_customers_q)).all()
    ]
    # По дням за последние 14 дней
    fourteen_ago = datetime.utcnow() - timedelta(days=14)
    by_day_q = (
        select(
            func.date(Analysis.created_at).label("day"),
            func.count(Analysis.id).label("cnt"),
        )
        .where(Analysis.created_at >= fourteen_ago)
        .group_by(func.date(Analysis.created_at))
        .order_by(func.date(Analysis.created_at))
    )
    by_day = [
        {"date": str(row[0]), "count": row[1]} for row in (await session.execute(by_day_q)).all()
    ]
    return {
        "users": {
            "total": total_users,
            "pilot": pilot_users,
            "subscribed": sub_users,
        },
        "analyses": {
            "total": total_analyses,
            "incomplete": incomplete,
            "with_high_risk": with_complaint,
            "last_24h": day_analyses,
            "last_7d": week_analyses,
            "avg_requirements": round(float(avg_req), 1),
        },
        "risk_distribution": risk_dist,
        "top_customers": top_customers,
        "by_day": by_day,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/recent")
async def recent(
    limit: int = 20,
    _admin: None = Depends(require_admin_key),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Последние N анализов (для live-ленты на дашборде)."""
    stmt = select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "lot_id": r.lot_id,
                "title": r.title,
                "customer": r.customer,
                "overall_risk": r.overall_risk,
                "n_requirements": r.n_requirements,
                "n_red_flags": r.n_red_flags,
                "incomplete": r.incomplete,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/token-check")
async def token_check(_admin: None = Depends(require_admin_key)) -> dict:
    """Minimal, safe Goszakup token validation using server-side configuration only."""
    settings = get_settings()
    token = (settings.goszakup_api_token or "").strip()
    base_url = (settings.goszakup_api_url or "").strip().rstrip("/")
    if not base_url:
        return {"status": "unavailable", "error_code": "GOSZAKUP_URL_MISSING"}
    if not token:
        return {"status": "configured", "error_code": "GOSZAKUP_CONFIG_MISSING"}

    candidate = urlsplit(base_url)
    if candidate.scheme not in {"http", "https"} or not candidate.netloc:
        return {"status": "unavailable", "error_code": "GOSZAKUP_URL_INVALID"}
    hostname = (candidate.hostname or "").lower()
    if not hostname or hostname.endswith("goszakup.gov.kz") is False:
        return {"status": "invalid", "error_code": "GOSZAKUP_HOST_UNTRUSTED"}
    if hostname in {"localhost", "127.0.0.1"} or hostname.startswith("127."):
        return {"status": "invalid", "error_code": "GOSZAKUP_HOST_UNTRUSTED"}

    graphql_url = f"{candidate.scheme}://{candidate.netloc}{candidate.path.rstrip('/')}/graphql"
    query = """
    query TestToken($id: Int!) {
      trd_buy(filters: { id: [$id] }, limit: 1) { id }
    }
    """
    payload = {"query": query, "variables": {"id": 1}}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=5.0, read=5.0),
            follow_redirects=False,
            headers={"User-Agent": "TendrAdmin/1.0"},
        ) as client:
            resp = await client.post(graphql_url, headers=headers, json=payload, timeout=5.0)
    except httpx.TimeoutException:
        return {"status": "unavailable", "error_code": "GOSZAKUP_TIMEOUT"}
    except httpx.RequestError:
        return {"status": "unavailable", "error_code": "GOSZAKUP_UNAVAILABLE"}

    if len(resp.content) > 64 * 1024:
        return {"status": "unavailable", "error_code": "GOSZAKUP_RESPONSE_TOO_LARGE"}
    if resp.status_code in {301, 302, 303, 307, 308}:
        return {"status": "invalid", "error_code": "GOSZAKUP_REDIRECT"}
    if resp.status_code == 401:
        return {"status": "invalid", "error_code": "GOSZAKUP_INVALID"}
    if resp.status_code in {403, 429}:
        return {"status": "unavailable", "error_code": "GOSZAKUP_FORBIDDEN"}
    if resp.status_code != 200:
        return {"status": "unavailable", "error_code": "GOSZAKUP_UNAVAILABLE"}

    try:
        body = resp.json()
    except ValueError:
        return {"status": "invalid", "error_code": "GOSZAKUP_BAD_RESPONSE"}

    if "errors" in body and body["errors"]:
        return {"status": "invalid", "error_code": "GOSZAKUP_INVALID"}
    if not isinstance(body, dict) or "data" not in body:
        return {"status": "invalid", "error_code": "GOSZAKUP_BAD_RESPONSE"}

    return {"status": "valid", "error_code": "GOSZAKUP_VALID"}
