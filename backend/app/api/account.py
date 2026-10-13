"""Эндпоинты аккаунта: квоты, discovery-подписки, профиль."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import require_admin_key
from app.core.config import get_settings
from app.core.supabase_auth import (
    SupabaseUser,
    require_supabase_user,
    supabase_client_id,
)
from app.db import get_db
from app.db import repo as db_repo
from app.db.models import (
    Analysis,
    DiscoverySubscription,
    Payment,
    Subscription,
    User,
    WorkspaceState,
)

router = APIRouter(prefix="/account", tags=["account"])


async def _user(session: AsyncSession, request: Request):
    cid = supabase_client_id(await require_supabase_user(request))
    user = await db_repo.get_user_by_web_id(session, cid)
    if not user:
        user = await db_repo.get_or_create_user(session, web_client_id=cid)
    return user


@router.get("/me")
async def get_current_account(
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Return the local account for a verified Supabase session."""
    identity = supabase_client_id(auth_user)
    user = await db_repo.get_or_create_user(session, web_client_id=identity)
    if auth_user.email and user.email != auth_user.email:
        user.email = auth_user.email
        await session.flush()
    quota = await db_repo.get_user_quota(session, user.id)
    return {
        "id": user.id,
        "email": user.email,
        "language": user.language,
        "company_name": user.company_name,
        "is_pilot": user.is_pilot,
        "is_subscribed": user.is_subscribed,
        "quota": quota,
    }


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


class WorkspaceStateRequest(BaseModel):
    payload: dict[str, Any] | list[Any]


@router.get("/workspace/{namespace}")
async def get_workspace_state(
    namespace: str,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if not namespace.replace("_", "").replace("-", "").isalnum() or len(namespace) > 64:
        raise HTTPException(status_code=400, detail="INVALID_WORKSPACE_NAMESPACE")
    user = await db_repo.get_or_create_user(
        session, web_client_id=supabase_client_id(auth_user)
    )
    row = await session.scalar(
        select(WorkspaceState).where(
            WorkspaceState.user_id == user.id,
            WorkspaceState.namespace == namespace,
        )
    )
    return {
        "namespace": namespace,
        "payload": row.payload if row else None,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


@router.put("/workspace/{namespace}")
async def put_workspace_state(
    namespace: str,
    body: WorkspaceStateRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if not namespace.replace("_", "").replace("-", "").isalnum() or len(namespace) > 64:
        raise HTTPException(status_code=400, detail="INVALID_WORKSPACE_NAMESPACE")
    encoded = json.dumps(body.payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="WORKSPACE_STATE_TOO_LARGE")
    user = await db_repo.get_or_create_user(
        session, web_client_id=supabase_client_id(auth_user)
    )
    row = await session.scalar(
        select(WorkspaceState).where(
            WorkspaceState.user_id == user.id,
            WorkspaceState.namespace == namespace,
        )
    )
    if row is None:
        row = WorkspaceState(user_id=user.id, namespace=namespace, payload=body.payload)
        session.add(row)
    else:
        row.payload = body.payload
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    return {"ok": True, "namespace": namespace}


PLAN_CATALOG = {
    "plus": {"monthly_limit": 150, "window_limit": 20, "amount_kzt": 10_000},
    "pro": {"monthly_limit": 400, "window_limit": 60, "amount_kzt": 25_000},
    "ultra": {"monthly_limit": 1200, "window_limit": 150, "amount_kzt": 56_000},
}


def _stripe_price_id(plan: str) -> str:
    settings = get_settings()
    return {
        "plus": settings.stripe_price_plus,
        "pro": settings.stripe_price_pro,
        "ultra": settings.stripe_price_ultra,
    }.get(plan, "")


@router.get("/billing/plans")
async def billing_plans() -> dict[str, Any]:
    settings = get_settings()
    configured = bool(settings.stripe_secret_key and settings.stripe_webhook_secret)
    return {
        "provider": "stripe" if configured else None,
        "plans": [
            {
                "id": plan,
                **limits,
                "checkout_available": bool(configured and _stripe_price_id(plan)),
            }
            for plan, limits in PLAN_CATALOG.items()
        ],
    }


class CheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(plus|pro|ultra)$")


@router.post("/billing/checkout")
async def create_billing_checkout(
    payload: CheckoutRequest,
    auth_user: Annotated[SupabaseUser, Depends(require_supabase_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Create a real hosted Stripe checkout; never activates a plan before webhook confirmation."""
    settings = get_settings()
    price_id = _stripe_price_id(payload.plan)
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret or not price_id:
        raise HTTPException(status_code=503, detail="BILLING_NOT_CONFIGURED")

    identity = supabase_client_id(auth_user)
    user = await db_repo.get_or_create_user(session, web_client_id=identity)
    form = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": settings.billing_success_url,
        "cancel_url": settings.billing_cancel_url,
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
        "metadata[plan]": payload.plan,
        "subscription_data[metadata][user_id]": str(user.id),
        "subscription_data[metadata][plan]": payload.plan,
    }
    if auth_user.email:
        form["customer_email"] = auth_user.email
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=form,
                headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
            )
        response.raise_for_status()
        checkout = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="BILLING_PROVIDER_ERROR") from exc

    checkout_id = str(checkout.get("id") or "")
    checkout_url = str(checkout.get("url") or "")
    if not checkout_id or not checkout_url.startswith("https://checkout.stripe.com/"):
        raise HTTPException(status_code=502, detail="BILLING_PROVIDER_ERROR")
    session.add(
        Payment(
            user_id=user.id,
            amount_kzt=PLAN_CATALOG[payload.plan]["amount_kzt"],
            method="stripe",
            status="pending",
            external_id=checkout_id,
            description=f"Tendr {payload.plan.title()}",
            raw_response={"checkout_session_id": checkout_id, "plan": payload.plan},
        )
    )
    await session.flush()
    return {"checkout_url": checkout_url}


def _verify_stripe_signature(payload: bytes, header: str, secret: str) -> bool:
    values: dict[str, list[str]] = {}
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key and value:
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values.get("t", [""])[0])
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp) > 300:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in values.get("v1", []))


def _stripe_period(subscription: dict[str, Any], *, now: datetime) -> tuple[datetime, datetime]:
    """Read the billing period from both older and current Stripe object shapes."""
    items = ((subscription.get("items") or {}).get("data") or [])
    starts = [subscription.get("current_period_start")]
    ends = [subscription.get("current_period_end")]
    for item in items:
        if isinstance(item, dict):
            starts.append(item.get("current_period_start"))
            ends.append(item.get("current_period_end"))

    def _timestamp(values: list[Any], fallback: datetime, *, latest: bool) -> datetime:
        valid = [int(value) for value in values if isinstance(value, (int, float)) and value > 0]
        if not valid:
            return fallback
        selected = max(valid) if latest else min(valid)
        return datetime.fromtimestamp(selected, UTC).replace(tzinfo=None)

    return (
        _timestamp(starts, now, latest=False),
        _timestamp(ends, now + timedelta(days=30), latest=True),
    )


async def _activate_stripe_subscription(
    session: AsyncSession,
    *,
    user: User,
    plan: str,
    external_id: str,
    starts_at: datetime,
    expires_at: datetime,
) -> Subscription:
    active_rows = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
        )
    )
    current: Subscription | None = None
    for subscription in active_rows.scalars().all():
        if external_id and subscription.external_id == external_id:
            current = subscription
        else:
            subscription.is_active = False
    if current is None:
        current = Subscription(user_id=user.id, plan=plan)
        session.add(current)
    current.plan = plan
    current.monthly_limit = PLAN_CATALOG[plan]["monthly_limit"]
    current.is_active = True
    current.starts_at = starts_at
    current.expires_at = expires_at
    current.external_id = external_id or current.external_id
    user.is_subscribed = True
    user.subscription_expires_at = expires_at
    return current


async def _deactivate_stripe_subscription(
    session: AsyncSession,
    *,
    external_id: str,
) -> None:
    row = await session.execute(
        select(Subscription).where(Subscription.external_id == external_id).limit(1)
    )
    subscription = row.scalar_one_or_none()
    if not subscription:
        return
    subscription.is_active = False
    user = await session.get(User, subscription.user_id)
    if not user:
        return
    other = await session.execute(
        select(Subscription.id).where(
            Subscription.user_id == user.id,
            Subscription.id != subscription.id,
            Subscription.is_active.is_(True),
            Subscription.expires_at > datetime.now(UTC).replace(tzinfo=None),
        ).limit(1)
    )
    if other.scalar_one_or_none() is None:
        user.is_subscribed = False
        user.subscription_expires_at = None


@router.post("/billing/webhook")
async def stripe_billing_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    """Activate a tariff only after a signed, paid Stripe event."""
    settings = get_settings()
    raw = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    if not settings.stripe_webhook_secret or not _verify_stripe_signature(
        raw, signature, settings.stripe_webhook_secret
    ):
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_SIGNATURE")
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD") from exc
    event_type = str(event.get("type") or "")
    stripe_object = ((event.get("data") or {}).get("object") or {})

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        status = str(stripe_object.get("status") or "")
        external_id = str(stripe_object.get("id") or "")
        if status not in {"active", "trialing"}:
            await _deactivate_stripe_subscription(session, external_id=external_id)
            return {"ok": True}
        metadata = stripe_object.get("metadata") or {}
        plan = str(metadata.get("plan") or "").lower()
        try:
            user_id = int(metadata.get("user_id"))
        except (TypeError, ValueError):
            return {"ok": True}
        if plan not in PLAN_CATALOG or not external_id:
            return {"ok": True}
        user = await session.get(User, user_id)
        if not user:
            return {"ok": True}
        now = datetime.utcnow()
        starts_at, expires_at = _stripe_period(stripe_object, now=now)
        await _activate_stripe_subscription(
            session,
            user=user,
            plan=plan,
            external_id=external_id,
            starts_at=starts_at,
            expires_at=expires_at,
        )
        return {"ok": True}

    if event_type == "customer.subscription.deleted":
        await _deactivate_stripe_subscription(
            session,
            external_id=str(stripe_object.get("id") or ""),
        )
        return {"ok": True}

    if event_type == "invoice.paid":
        parent = stripe_object.get("parent") or {}
        details = parent.get("subscription_details") or {}
        external_id = str(
            stripe_object.get("subscription")
            or details.get("subscription")
            or ""
        )
        row = await session.execute(
            select(Subscription).where(Subscription.external_id == external_id).limit(1)
        )
        subscription = row.scalar_one_or_none()
        if not subscription:
            return {"ok": True}
        period_ends = []
        for line in ((stripe_object.get("lines") or {}).get("data") or []):
            if isinstance(line, dict):
                end = (line.get("period") or {}).get("end")
                if isinstance(end, (int, float)) and end > 0:
                    period_ends.append(int(end))
        if period_ends:
            subscription.expires_at = datetime.fromtimestamp(
                max(period_ends), UTC
            ).replace(tzinfo=None)
        subscription.is_active = True
        user = await session.get(User, subscription.user_id)
        if user:
            user.is_subscribed = True
            user.subscription_expires_at = subscription.expires_at
        invoice_id = str(stripe_object.get("id") or "")
        existing_payment = await session.execute(
            select(Payment).where(Payment.external_id == invoice_id).limit(1)
        )
        if invoice_id and existing_payment.scalar_one_or_none() is None:
            session.add(
                Payment(
                    user_id=subscription.user_id,
                    amount_kzt=PLAN_CATALOG.get(subscription.plan, {}).get("amount_kzt", 0),
                    method="stripe",
                    status="succeeded",
                    external_id=invoice_id,
                    description=f"Tendr {subscription.plan.title()} renewal",
                    completed_at=datetime.utcnow(),
                    raw_response={"invoice_id": invoice_id, "subscription_id": external_id},
                )
            )
        return {"ok": True}

    if event_type != "checkout.session.completed":
        return {"ok": True}
    checkout = stripe_object
    if checkout.get("payment_status") != "paid":
        return {"ok": True}
    metadata = checkout.get("metadata") or {}
    plan = str(metadata.get("plan") or "").lower()
    try:
        user_id = int(metadata.get("user_id") or checkout.get("client_reference_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD") from exc
    if plan not in PLAN_CATALOG:
        raise HTTPException(status_code=400, detail="INVALID_WEBHOOK_PAYLOAD")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")

    checkout_id = str(checkout.get("id") or "")
    payment_row = await session.execute(
        select(Payment).where(Payment.external_id == checkout_id).limit(1)
    )
    payment = payment_row.scalar_one_or_none()
    if payment and payment.status == "succeeded":
        return {"ok": True}
    now = datetime.utcnow()
    if not payment:
        payment = Payment(
            user_id=user.id,
            amount_kzt=PLAN_CATALOG[plan]["amount_kzt"],
            method="stripe",
            external_id=checkout_id,
            description=f"Tendr {plan.title()}",
        )
        session.add(payment)
    payment.status = "succeeded"
    payment.completed_at = now
    payment.raw_response = {"checkout_session_id": checkout_id, "plan": plan, "paid": True}

    expires_at = now + timedelta(days=30)
    await _activate_stripe_subscription(
        session,
        user=user,
        plan=plan,
        external_id=str(checkout.get("subscription") or checkout_id),
        starts_at=now,
        expires_at=expires_at,
    )
    await session.flush()
    return {"ok": True}


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
    normalized_keywords = ", ".join(
        dict.fromkeys(part.strip() for part in payload.keywords.split(",") if part.strip())
    )
    if not normalized_keywords:
        raise HTTPException(status_code=422, detail="KEYWORDS_REQUIRED")
    existing = (
        await session.execute(
            select(DiscoverySubscription).where(
                DiscoverySubscription.user_id == user.id,
                DiscoverySubscription.keywords == normalized_keywords,
                DiscoverySubscription.channel == payload.channel,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        sub = DiscoverySubscription(
            user_id=user.id,
            keywords=normalized_keywords,
            channel=payload.channel,
        )
        session.add(sub)
    else:
        sub = existing
    sub.category = payload.category
    sub.region = payload.region
    sub.min_budget_kzt = payload.min_budget_kzt
    sub.max_budget_kzt = payload.max_budget_kzt
    sub.is_active = True
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
    reason: str = Field(default="Administrative quota correction", min_length=1, max_length=255)


@router.post("/admin/reset-quota")
async def admin_reset_quota(
    payload: ResetQuotaRequest,
    _admin: None = Depends(require_admin_key),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сбросить счётчик использований в этом месяце (для теста).

    В будущем — удалить этот эндпоинт или закрыть.
    """
    from sqlalchemy import and_, delete, select

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

    from datetime import UTC, datetime
    from app.db.models import QuotaResetAudit
    now = datetime.now(UTC).replace(tzinfo=None)
    user.quota_reset_at = now
    session.add(QuotaResetAudit(user_id=user.id, reason=payload.reason, actor="admin-api", occurred_at=now))
    await session.flush()
    return {"ok": True, "user_id": user.id, "reset_for_month": now.strftime("%Y-%m")}
