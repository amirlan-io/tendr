"""Repository для работы с БД (users, analyses, subscriptions, payments).

Используется вместо in-memory result_store, чтобы история не терялась.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_id import validate_client_id
from app.core.config import get_settings
from app.db.models import Analysis, Payment, QuotaReservation, Subscription, User


class QuotaLimitExceeded(RuntimeError):
    """Внутреннее исключение при исчерпании квоты."""


PLAN_LIMITS: dict[str, tuple[int, int]] = {
    "free": (3, 3),
    "plus": (150, 20),
    "pro": (400, 60),
    "ultra": (1200, 150),
    "pilot": (999, 999),
    # Старое название подписки сохраняем для обратной совместимости.
    "monthly": (999, 60),
}


def _normalize_utc(dt: datetime | None) -> datetime:
    if dt is None:
        dt = datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return _normalize_utc(dt).replace(tzinfo=None)


async def _run_in_transaction(session: AsyncSession, callback):
    if session.in_transaction():
        return await callback()
    async with session.begin():
        return await callback()


def _month_start_utc(now: datetime | None = None) -> datetime:
    now = _normalize_utc(now)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


async def _current_reserved_amount(
    session: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
    month_key: str | None = None,
) -> int:
    now = _normalize_utc(now)
    now_naive = now.replace(tzinfo=None)
    month_key = month_key or now.strftime("%Y-%m")
    stmt = select(func.coalesce(func.sum(QuotaReservation.amount), 0)).where(
        and_(
            QuotaReservation.user_id == user_id,
            QuotaReservation.month_key == month_key,
            QuotaReservation.status == "reserved",
            QuotaReservation.expires_at > now_naive,
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar() or 0)


async def _usage_in_rolling_window(
    session: AsyncSession,
    user_id: int,
    *,
    now: datetime,
    hours: int = 5,
) -> tuple[int, int]:
    since = (now - timedelta(hours=hours)).replace(tzinfo=None)
    now_naive = now.replace(tzinfo=None)
    analysis_result = await session.execute(
        select(func.count(Analysis.id)).where(
            Analysis.user_id == user_id,
            Analysis.created_at >= since,
        )
    )
    confirmed_result = await session.execute(
        select(func.coalesce(func.sum(QuotaReservation.amount), 0)).where(
            QuotaReservation.user_id == user_id,
            QuotaReservation.status == "confirmed",
            QuotaReservation.confirmed_at >= since,
        )
    )
    reserved_result = await session.execute(
        select(func.coalesce(func.sum(QuotaReservation.amount), 0)).where(
            QuotaReservation.user_id == user_id,
            QuotaReservation.status == "reserved",
            QuotaReservation.reserved_at >= since,
            QuotaReservation.expires_at > now_naive,
        )
    )
    # Analysis history is de-duplicated by lot_id, whereas quota consumption is
    # per run.  max() keeps old rows (created before the reservation ledger)
    # compatible without charging modern runs twice.
    used = max(
        int(analysis_result.scalar() or 0),
        int(confirmed_result.scalar() or 0),
    )
    return used, int(reserved_result.scalar() or 0)


async def _resolve_user_plan_limits(
    session: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
) -> tuple[str, int, int]:
    user = await session.get(User, user_id)
    if not user:
        return "free", *PLAN_LIMITS["free"]
    if user.is_pilot:
        return "pilot", *PLAN_LIMITS["pilot"]

    now_naive = _normalize_utc(now).replace(tzinfo=None)
    row = await session.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
            Subscription.starts_at <= now_naive,
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now_naive),
        )
        .order_by(Subscription.starts_at.desc())
        .limit(1)
    )
    subscription = row.scalar_one_or_none()
    if subscription:
        plan = subscription.plan.lower()
        default_monthly, burst = PLAN_LIMITS.get(plan, (subscription.monthly_limit, 60))
        return plan, int(subscription.monthly_limit or default_monthly), burst
    return "free", int(get_settings().free_tier_applications_per_month), PLAN_LIMITS["free"][1]


async def cleanup_expired_quota_reservations(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Освободить просроченные резервирования."""
    now = _normalize_utc(now)
    now_naive = now.replace(tzinfo=None)
    rows = await session.execute(
        select(QuotaReservation).where(
            and_(
                QuotaReservation.status == "reserved",
                QuotaReservation.expires_at <= now_naive,
            )
        )
    )
    expired = rows.scalars().all()
    for reservation in expired:
        reservation.status = "released"
        # Наивное UTC: в колонку TIMESTAMP WITHOUT TIME ZONE нельзя
        # писать aware-значение (ошибка asyncpg про offset-aware/naive).
        reservation.released_at = now_naive
        reservation.release_reason = "expired"
    if expired:
        await session.flush()
    return len(expired)


async def reserve_user_quota(
    session: AsyncSession,
    user_id: int,
    *,
    operation_key: str,
    amount: int = 1,
    ttl_seconds: int = 300,
    limit: int | None = None,
    now_override: datetime | None = None,
) -> dict[str, Any]:
    """Atomically reserve quota for a single user operation.

    Гонка закрыта блокировкой строки пользователя (`SELECT ... FOR UPDATE`),
    а не только общей транзакцией: при READ COMMITTED (дефолт PostgreSQL) две
    параллельные транзакции читали бы одинаковые used/reserved и обе вставили
    бы резервацию, обойдя лимит. Блокировка строки сериализует резервирование
    для одного пользователя; конкурент ждёт и после освобождения видит
    обновлённые данные (аудит 2026-10-03, P0 #2).
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    now = _normalize_utc(now_override)
    month_key = now.strftime("%Y-%m")
    now_naive = now.replace(tzinfo=None)
    effective_limit = limit if limit is not None else await _resolve_user_limit(session, user_id)

    async def _reserve() -> dict[str, Any]:
        await cleanup_expired_quota_reservations(session, now=now)
        # Блокировка строки: следующий запрос по тому же пользователю
        # дождётся завершения этой транзакции.
        user = (
            await session.execute(select(User).where(User.id == user_id).with_for_update())
        ).scalar_one_or_none()
        if user is None:
            raise LookupError(f"User {user_id} not found")
        used_this_month = await count_analyses_this_month(session, user_id, now_override=now)
        reserved_this_month = await _current_reserved_amount(
            session,
            user_id,
            now=now,
            month_key=month_key,
        )
        if used_this_month + reserved_this_month + amount > effective_limit:
            raise QuotaLimitExceeded(f"Quota limit exceeded for user {user_id}")
        _, _, burst_limit = await _resolve_user_plan_limits(session, user_id, now=now)
        used_in_window, reserved_in_window = await _usage_in_rolling_window(
            session, user_id, now=now
        )
        if used_in_window + reserved_in_window + amount > burst_limit:
            raise QuotaLimitExceeded(f"Five-hour quota exceeded for user {user_id}")

        reservation = QuotaReservation(
            user_id=user_id,
            reservation_key=uuid.uuid4().hex,
            operation_key=operation_key[:128],
            amount=int(amount),
            month_key=month_key,
            status="reserved",
            reserved_at=now_naive,
            expires_at=now_naive + timedelta(seconds=max(1, int(ttl_seconds))),
        )
        session.add(reservation)
        await session.flush()
        return {
            "status": "reserved",
            "reservation_key": reservation.reservation_key,
            "amount": reservation.amount,
            "limit": effective_limit,
            "expires_at": reservation.expires_at.isoformat(),
        }

    return await _run_in_transaction(session, _reserve)


async def confirm_user_quota(
    session: AsyncSession,
    user_id: int,
    reservation_key: str | None = None,
    *,
    now_override: datetime | None = None,
) -> bool:
    """Confirm a reservation; idempotent."""
    if reservation_key is None:
        raise ValueError("reservation_key is required")

    now = _normalize_utc(now_override)
    now_naive = now.replace(tzinfo=None)

    async def _confirm() -> bool:
        result = await session.execute(
            select(QuotaReservation).where(
                and_(
                    QuotaReservation.user_id == user_id,
                    QuotaReservation.reservation_key == reservation_key,
                )
            )
        )
        reservation = result.scalar_one_or_none()
        if not reservation:
            return False
        if reservation.status == "confirmed":
            return False
        if reservation.status in {"released", "expired"}:
            return False
        if reservation.expires_at is not None and reservation.expires_at <= now_naive:
            reservation.status = "released"
            reservation.released_at = now_naive
            reservation.release_reason = "expired"
            await session.flush()
            return False

        reservation.status = "confirmed"
        reservation.confirmed_at = now_naive
        await session.flush()
        return True

    return await _run_in_transaction(session, _confirm)


async def release_user_quota(
    session: AsyncSession,
    user_id: int,
    reservation_key: str | None = None,
    *,
    now_override: datetime | None = None,
) -> bool:
    """Release a reservation; idempotent."""
    if reservation_key is None:
        raise ValueError("reservation_key is required")

    now = _normalize_utc(now_override)

    async def _release() -> bool:
        result = await session.execute(
            select(QuotaReservation).where(
                and_(
                    QuotaReservation.user_id == user_id,
                    QuotaReservation.reservation_key == reservation_key,
                )
            )
        )
        reservation = result.scalar_one_or_none()
        if not reservation:
            return False
        if reservation.status in {"released", "confirmed"}:
            return False
        reservation.status = "released"
        # Колонка TIMESTAMP WITHOUT TIME ZONE: aware-значение приводит
        # asyncpg к ошибке "can't subtract offset-naive and offset-aware".
        reservation.released_at = _utc_naive(now)
        reservation.release_reason = "manual"
        await session.flush()
        return True

    return await _run_in_transaction(session, _release)


async def _resolve_user_limit(session: AsyncSession, user_id: int) -> int:
    _, monthly, _ = await _resolve_user_plan_limits(session, user_id)
    return monthly



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


async def count_analyses_this_month(
    session: AsyncSession,
    user_id: int,
    *,
    now_override: datetime | None = None,
) -> int:
    """Сколько анализов юзер сделал в текущем месяце, в UTC."""
    now = _normalize_utc(now_override)
    start_of_month = _month_start_utc(now).replace(tzinfo=None)
    stmt = select(func.count(Analysis.id)).where(
        and_(Analysis.user_id == user_id, Analysis.created_at >= start_of_month)
    )
    result = await session.execute(stmt)
    history_count = int(result.scalar_one() or 0)
    confirmed = await session.execute(
        select(func.coalesce(func.sum(QuotaReservation.amount), 0)).where(
            QuotaReservation.user_id == user_id,
            QuotaReservation.status == "confirmed",
            QuotaReservation.confirmed_at >= start_of_month,
        )
    )
    return max(history_count, int(confirmed.scalar_one() or 0))


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
    offset: int = 0,
) -> list[Analysis]:
    """История анализов пользователя (свежие первые)."""
    stmt = (
        select(Analysis)
        .where(Analysis.user_id == user_id)
        .order_by(Analysis.created_at.desc())
        .offset(offset)
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


async def get_user_quota(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int | None = None,
    now_override: datetime | None = None,
) -> dict[str, Any]:
    """Получить квоту пользователя: лимит + использовано + активные резервы."""
    user = await session.get(User, user_id)
    now = _normalize_utc(now_override)
    month_key = now.strftime("%Y-%m")

    if not user:
        default = 3
        return {
            "limit": default,
            "used": 0,
            "used_this_month": 0,
            "reserved_this_month": 0,
            "remaining": default,
            "is_pilot": False,
            "is_subscribed": False,
            "subscription_expires_at": None,
            "monthly_limit": default,
            "month_key": month_key,
            "plan": "free",
            "window_hours": 5,
            "window_limit": 3,
            "used_last_5_hours": 0,
            "reserved_last_5_hours": 0,
            "remaining_last_5_hours": 3,
            "window_resets_at": None,
        }

    plan, plan_monthly_limit, burst_limit = await _resolve_user_plan_limits(
        session, user_id, now=now
    )
    effective_limit = limit if limit is not None else plan_monthly_limit
    used = await count_analyses_this_month(session, user_id, now_override=now)
    reserved = await _current_reserved_amount(session, user_id, now=now, month_key=month_key)
    remaining = max(0, effective_limit - used - reserved)
    used_in_window, reserved_in_window = await _usage_in_rolling_window(
        session, user_id, now=now
    )
    window_remaining = max(0, burst_limit - used_in_window - reserved_in_window)
    oldest_analysis = await session.execute(
        select(func.min(Analysis.created_at))
        .where(
            Analysis.user_id == user_id,
            Analysis.created_at >= (now - timedelta(hours=5)).replace(tzinfo=None),
        )
    )
    oldest_confirmation = await session.execute(
        select(func.min(QuotaReservation.confirmed_at)).where(
            QuotaReservation.user_id == user_id,
            QuotaReservation.status == "confirmed",
            QuotaReservation.confirmed_at >= (now - timedelta(hours=5)).replace(tzinfo=None),
        )
    )
    candidates = [
        value
        for value in (oldest_analysis.scalar_one_or_none(), oldest_confirmation.scalar_one_or_none())
        if value is not None
    ]
    oldest_used_at = min(candidates) if candidates else None
    window_resets_at = (
        _normalize_utc(oldest_used_at + timedelta(hours=5)).isoformat()
        if oldest_used_at
        else None
    )

    return {
        "limit": effective_limit,
        "used": used,
        "used_this_month": used,
        "reserved_this_month": reserved,
        "remaining": remaining,
        "is_pilot": user.is_pilot,
        "is_subscribed": user.is_subscribed,
        "subscription_expires_at": user.subscription_expires_at.isoformat()
        if user.subscription_expires_at
        else None,
        "monthly_limit": effective_limit,
        "month_key": month_key,
        "plan": plan,
        "window_hours": 5,
        "window_limit": burst_limit,
        "used_last_5_hours": used_in_window,
        "reserved_last_5_hours": reserved_in_window,
        "remaining_last_5_hours": window_remaining,
        "window_resets_at": window_resets_at,
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
            - result_json (dict, опционально) — полный результат анализа;
              без него запись содержит только метаданные и не годится
              для генерации документов и подбора поставщиков

    Returns:
        Созданная Analysis или None, если не удалось сохранить.
    """
    try:
        lot_id = str(entry.get("lot_id") or "unknown")
        # Полный результат анализа. Без него result_json остаётся заглушкой
        # без требований ТЗ, и от него зависят /download и агент поставщиков.
        full_result = _json_safe(entry.get("result_json"))
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
            if isinstance(full_result, dict) and full_result:
                existing.result_json = full_result
            await session.flush()
            return existing

        analysis = Analysis(
            user_id=user_id,
            lot_id=lot_id,
            source_url=entry.get("url"),
            title=(entry.get("title") or "")[:500],
            customer=str((full_result or {}).get("lot", {}).get("customer") or "")[:500],
            method=str((full_result or {}).get("lot", {}).get("method") or "other"),
            budget_kzt=(full_result or {}).get("lot", {}).get("budget_kzt"),
            result_json=full_result if isinstance(full_result, dict) and full_result else entry,
            n_requirements=int(entry.get("n_requirements") or 0),
            n_red_flags=int(entry.get("n_red_flags") or 0),
            overall_risk=str(entry.get("overall_risk") or "needs_review"),
            incomplete=bool((full_result or {}).get("incomplete", False)),
        )
        session.add(analysis)
        await session.flush()
        return analysis
    except Exception as exc:
        # Не падать при ошибке логирования — это вспомогательная операция.
        # Но молчать нельзя: именно из-за молчания терялись результаты
        # анализа, и скачивание документов отдавало 404.
        logger.warning("history push failed for lot {}: {}", lot_id, exc)
        return None


def _json_safe(value: Any) -> dict[str, Any] | None:
    """Привести структуру к JSON-совместимому виду.

    В полном результате анализа есть datetime/date, которые JSONB не
    принимает («Object of type datetime is not JSON serializable»).
    """
    if not isinstance(value, dict):
        return None

    def _convert(item: Any) -> Any:
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, dict):
            return {str(k): _convert(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [_convert(v) for v in item]
        return item

    return {str(k): _convert(v) for k, v in value.items()}


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
