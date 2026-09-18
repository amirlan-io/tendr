"""Repository для работы с БД (users, analyses, subscriptions, payments).

Используется вместо in-memory result_store, чтобы история не терялась.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_id import validate_client_id
from app.core.config import get_settings
from app.db.models import Analysis, Payment, Subscription, User


async def get_or_create_user(
    session: AsyncSession,
    *,
    telegram_id: int | None = None,
    web_client_id: str | None = None,
) -> User:
    """Найти существующего юзера или создать нового."""
    if telegram_id:
        stmt = select(User).where(User.telegram_id == telegram_id)
    elif web_client_id:
        if not validate_client_id(web_client_id):
            raise ValueError("Invalid web client id")
        stmt = select(User).where(User.web_client_id == web_client_id)
    else:
        raise ValueError("Either telegram_id or web_client_id required")

    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        telegram_id=telegram_id,
        web_client_id=web_client_id,
    )
    session.add(user)
    await session.flush()
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_web_id(session: AsyncSession, web_client_id: str) -> User | None:
    stmt = select(User).where(User.web_client_id == web_client_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def count_analyses_this_month(session: AsyncSession, user_id: int) -> int:
    """Сколько анализов юзер сделал в текущем месяце."""
    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1)
    stmt = select(func.count(Analysis.id)).where(
        and_(Analysis.user_id == user_id, Analysis.created_at >= start_of_month)
    )
    result = await session.execute(stmt)
    return result.scalar_one() or 0


async def save_analysis(
    session: AsyncSession,
    user_id: int,
    *,
    lot_id: str,
    result_data: dict[str, Any],
    source_url: str | None = None,
    source_id: str | None = None,
    ttl_days: int = 30,
) -> Analysis:
    """Сохранить результат анализа в БД."""
    lot = result_data.get("lot") or {}
    legal = result_data.get("legal") or {}
    analysis = Analysis(
        user_id=user_id,
        lot_id=lot_id,
        source_url=source_url,
        source_id=source_id,
        title=(lot.get("title") or "")[:500],
        customer=(lot.get("customer") or "")[:500],
        method=lot.get("method", "other"),
        budget_kzt=lot.get("budget_kzt"),
        deadline=lot.get("deadline"),
        result_json=result_data,
        n_requirements=len(lot.get("requirements") or []),
        n_red_flags=len(lot.get("red_flags") or []),
        overall_risk=(legal.get("overall_risk") if isinstance(legal, dict) else "needs_review")
        or "needs_review",
        incomplete=result_data.get("incomplete", False),
        expires_at=datetime.utcnow() + timedelta(days=ttl_days),
    )
    session.add(analysis)
    await session.flush()
    return analysis


async def get_user_history(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
) -> list[Analysis]:
    """История анализов пользователя (свежие первые)."""
    stmt = (
        select(Analysis)
        .where(Analysis.user_id == user_id)
        .order_by(Analysis.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_analysis_by_lot(session: AsyncSession, user_id: int, lot_id: str) -> Analysis | None:
    """Найти последний анализ по lot_id для юзера."""
    stmt = (
        select(Analysis)
        .where(and_(Analysis.user_id == user_id, Analysis.lot_id == lot_id))
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_quota(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Получить квоту пользователя: лимит + использовано.

    Возвращает словарь с ключами:
        - limit: месячный лимит анализов
        - used: сколько использовано в этом месяце
        - remaining: сколько осталось
        - is_pilot: является ли пилотным пользователем
        - is_subscribed: есть ли активная подписка
        - subscription_expires_at: ISO-дата окончания подписки или None
        - monthly_limit: alias для limit (для совместимости со старым кодом)
        - used_this_month: alias для used (для совместимости со старым кодом)
    """
    user = await session.get(User, user_id)
    if not user:
        return {
            "limit": 3,
            "used": 0,
            "remaining": 3,
            "is_pilot": False,
            "is_subscribed": False,
            "subscription_expires_at": None,
            "monthly_limit": 3,
            "used_this_month": 0,
        }

    used = await count_analyses_this_month(session, user_id)
    s = get_settings()

    if user.is_pilot:
        limit = s.pilot_free_tier_applications_per_month
    elif (
        user.is_subscribed
        and user.subscription_expires_at
        and user.subscription_expires_at > datetime.utcnow()
    ):
        limit = 999  # подписчикам — безлимит
    else:
        limit = s.free_tier_applications_per_month

    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "is_pilot": user.is_pilot,
        "is_subscribed": user.is_subscribed,
        "subscription_expires_at": user.subscription_expires_at.isoformat()
        if user.subscription_expires_at
        else None,
        # aliases for backward compatibility (lots.py использует monthly_limit/used_this_month)
        "monthly_limit": limit,
        "used_this_month": used,
    }


async def push_history(
    session: AsyncSession,
    user_id: int,
    entry: dict[str, Any],
) -> Analysis | None:
    """Сохранить запись в историю анализов пользователя.

    Используется API-эндпоинтом /api/lots/analyze для логирования
    запуска анализа (даже если сам анализ уже сохранён через save_analysis).

    Args:
        session: асинхронная сессия БД
        user_id: ID пользователя
        entry: словарь с полями:
            - lot_id (str)
            - title (str, опционально)
            - url (str, опционально) — сохраняется в source_url
            - created_at (ISO str, опционально)
            - overall_risk (str, опционально)
            - n_requirements (int, опционально)
            - n_red_flags (int, опционально)

    Returns:
        Созданная Analysis или None, если не удалось сохранить.
    """
    try:
        lot_id = str(entry.get("lot_id") or "unknown")
        # Не создаём дубли — просто обновим существующую запись если она есть
        existing = await get_analysis_by_lot(session, user_id, lot_id)
        if existing:
            # Обновим поля если они переданы
            if entry.get("title"):
                existing.title = str(entry["title"])[:500]
            if entry.get("url"):
                existing.source_url = str(entry["url"])
            if entry.get("overall_risk"):
                existing.overall_risk = str(entry["overall_risk"])
            if "n_requirements" in entry:
                try:
                    existing.n_requirements = int(entry["n_requirements"])
                except (TypeError, ValueError):
                    pass
            if "n_red_flags" in entry:
                try:
                    existing.n_red_flags = int(entry["n_red_flags"])
                except (TypeError, ValueError):
                    pass
            await session.flush()
            return existing

        analysis = Analysis(
            user_id=user_id,
            lot_id=lot_id,
            source_url=entry.get("url"),
            title=(entry.get("title") or "")[:500],
            customer="",
            method="other",
            result_json=entry,
            n_requirements=int(entry.get("n_requirements") or 0),
            n_red_flags=int(entry.get("n_red_flags") or 0),
            overall_risk=str(entry.get("overall_risk") or "needs_review"),
            incomplete=False,
        )
        session.add(analysis)
        await session.flush()
        return analysis
    except Exception:
        # Не падать при ошибке логирования — это вспомогательная операция.
        return None


async def record_payment(
    session: AsyncSession,
    user_id: int,
    *,
    amount_kzt: float,
    method: str,
    external_id: str | None = None,
    description: str | None = None,
    status: str = "pending",
) -> Payment:
    """Записать платёж."""
    payment = Payment(
        user_id=user_id,
        amount_kzt=amount_kzt,
        method=method,
        external_id=external_id,
        description=description,
        status=status,
    )
    session.add(payment)
    await session.flush()
    return payment


async def activate_subscription(
    session: AsyncSession,
    user_id: int,
    *,
    plan: str = "monthly",
    days: int = 30,
    external_id: str | None = None,
) -> Subscription:
    """Активировать подписку пользователю."""
    now = datetime.utcnow()
    sub = Subscription(
        user_id=user_id,
        plan=plan,
        monthly_limit=999,
        is_active=True,
        starts_at=now,
        expires_at=now + timedelta(days=days),
        external_id=external_id,
    )
    session.add(sub)

    # Обновить флаг в User
    user = await session.get(User, user_id)
    if user:
        user.is_subscribed = True
        user.subscription_expires_at = sub.expires_at

    await session.flush()
    return sub
