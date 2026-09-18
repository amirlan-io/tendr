"""Admin API: статистика для дашборда пилота."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.db.models import Analysis, User

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_key(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    settings = get_settings()
    configured = (settings.admin_api_key or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        raise HTTPException(status_code=401, detail="Invalid admin key")


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
    """Проверить работоспособность токена goszakup.

    Использует тестовый endpoint OWS API. Если токен рабочий — 200.
    """
    import httpx
    settings = get_settings()
    token = settings.goszakup_api_token
    url = settings.goszakup_api_url.rstrip("/")

    if not token or token == "mock-test-token-12345":
        return {
            "status": "no_token",
            "message": "GOSZAKUP_API_TOKEN не настроен в .env. Получи токен и вставь его туда.",
            "token_present": bool(token),
        }

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    test_url = f"{url}/v3/lots/17266377"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(test_url, headers=headers)
    except Exception as e:
        return {
            "status": "network_error",
            "message": f"Ошибка сети: {e}",
            "token_present": True,
        }

    if resp.status_code == 200:
        data = resp.json()
        return {
            "status": "ok",
            "message": "Токен рабочий! API возвращает 200 OK.",
            "token_present": True,
            "api_url": url,
            "response_keys": list(data.keys())[:10],
        }
    if resp.status_code == 401:
        return {
            "status": "unauthorized",
            "message": "Токен невалидный или просрочен.",
            "token_present": True,
            "response_status": 401,
        }
    if resp.status_code == 403:
        return {
            "status": "forbidden",
            "message": "Токен валидный, но нет доступа к этому endpoint.",
            "token_present": True,
            "response_status": 403,
        }
    if resp.status_code == 404:
        return {
            "status": "not_found",
            "message": "Токен рабочий, но лот 17266377 не найден.",
            "token_present": True,
            "response_status": 404,
        }
    return {
        "status": "error",
        "message": f"API вернул {resp.status_code}. {resp.text[:200]}",
        "token_present": True,
        "response_status": resp.status_code,
    }
