"""Tariff policy: fixed windows, no monthly cap, entitlements and checkout price safety."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db import Base, repo
from app.db.models import User, Subscription, Analysis
from app.core.config import get_settings
from app.core.supabase_auth import SupabaseUser
from app.api import account, lots

NOW = datetime(2026, 10, 31, 23, 30, tzinfo=UTC)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def subscribed(session, plan="plus", now=NOW):
    user = User(web_client_id="supabase_11111111111141118111111111111111")
    session.add(user)
    await session.flush()
    session.add(
        Subscription(
            user_id=user.id,
            plan=plan,
            monthly_limit=1,
            starts_at=(now - timedelta(days=1)).replace(tzinfo=None),
            expires_at=(now + timedelta(days=30)).replace(tzinfo=None),
            is_active=True,
        )
    )
    await session.flush()
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan,price,limit", [("plus", 5000, 5), ("pro", 10000, 10), ("ultra", 25000, 20)]
)
async def test_tariffs_have_only_fixed_five_hour_allowance(session, plan, price, limit):
    user = await subscribed(session, plan)
    public = await account.billing_plans()
    entry = next(p for p in public["plans"] if p["id"] == plan)
    assert (entry["amount_kzt"], entry["window_limit"]) == (price, limit)
    assert entry["monthly_limit"] is None and entry["unit"] == "analysis"
    for i in range(limit):
        r = await repo.reserve_user_quota(
            session, user.id, operation_key=f"run:{i}", now_override=NOW
        )
        await repo.confirm_user_quota(session, user.id, r["reservation_key"], now_override=NOW)
    q = await repo.get_user_quota(session, user.id, now_override=NOW)
    assert q["remaining"] == 0 and q["monthly_limit"] is None
    with pytest.raises(repo.QuotaLimitExceeded):
        await repo.reserve_user_quota(session, user.id, operation_key="overflow", now_override=NOW)
    # All allowance is restored together, despite the legacy monthly_limit=1.
    r = await repo.reserve_user_quota(
        session, user.id, operation_key="next-window", now_override=NOW + timedelta(hours=5)
    )
    assert r["amount"] == 1


@pytest.mark.asyncio
async def test_fixed_window_starts_with_reservation_and_survives_month_change(session):
    user = await subscribed(session)
    assert (await repo.get_user_quota(session, user.id, now_override=NOW))[
        "window_resets_at"
    ] is None
    first = await repo.reserve_user_quota(
        session, user.id, operation_key="first", now_override=NOW, ttl_seconds=3600
    )
    await repo.confirm_user_quota(
        session, user.id, first["reservation_key"], now_override=NOW + timedelta(minutes=10)
    )
    await repo.reserve_user_quota(
        session,
        user.id,
        operation_key="second",
        now_override=NOW + timedelta(hours=4),
        ttl_seconds=3600,
    )
    q = await repo.get_user_quota(
        session, user.id, now_override=NOW + timedelta(hours=4, minutes=59)
    )
    assert q["used"] == 1 and q["reserved"] == 1 and q["remaining"] == 3
    assert q["window_resets_at"] == (NOW + timedelta(hours=5)).isoformat()
    fresh = await repo.get_user_quota(session, user.id, now_override=NOW + timedelta(hours=5))
    assert fresh["remaining"] == 5 and fresh["window_resets_at"] is None


@pytest.mark.asyncio
async def test_failed_operation_refunds_without_moving_reset_time(session):
    user = await subscribed(session)
    first = await repo.reserve_user_quota(
        session, user.id, operation_key="failed", now_override=NOW
    )
    await repo.release_user_quota(session, user.id, first["reservation_key"], now_override=NOW)
    second = await repo.reserve_user_quota(
        session, user.id, operation_key="retry", now_override=NOW + timedelta(hours=1)
    )
    q = await repo.get_user_quota(session, user.id, now_override=NOW + timedelta(hours=1))
    assert q["used"] == 0 and q["reserved"] == 1
    assert q["window_resets_at"] == (NOW + timedelta(hours=5)).isoformat()
    assert second["reservation_key"] != first["reservation_key"]


@pytest.mark.asyncio
async def test_late_confirmation_does_not_charge_new_window(session):
    user = await subscribed(session)
    old = await repo.reserve_user_quota(
        session, user.id, operation_key="old", now_override=NOW, ttl_seconds=86400
    )
    await repo.reserve_user_quota(
        session, user.id, operation_key="new", now_override=NOW + timedelta(hours=5)
    )
    await repo.confirm_user_quota(
        session, user.id, old["reservation_key"], now_override=NOW + timedelta(hours=5)
    )
    q = await repo.get_user_quota(session, user.id, now_override=NOW + timedelta(hours=5))
    assert q["used"] == 0 and q["reserved"] == 1 and q["remaining"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan,feature,allowed",
    [
        ("plus", "documents", False),
        ("plus", "deep_analysis", False),
        ("plus", "suppliers", False),
        ("pro", "documents", True),
        ("pro", "deep_analysis", True),
        ("pro", "suppliers", False),
        ("ultra", "suppliers", True),
    ],
)
async def test_entitlements_are_enforced_on_server(session, plan, feature, allowed):
    user = await subscribed(session, plan, datetime.now(UTC))
    if allowed:
        await repo.require_plan_feature(session, user.id, feature)
    else:
        with pytest.raises(HTTPException) as error:
            await repo.require_plan_feature(session, user.id, feature)
        assert error.value.status_code == 403
    assert (await repo.get_user_quota(session, user.id))["used"] == 0


@pytest.mark.asyncio
async def test_comparison_cannot_read_other_account_or_spend_quota(session):
    user = await subscribed(session, "pro", datetime.now(UTC))
    other = User(web_client_id="other_private_account")
    session.add(other)
    await session.flush()
    session.add_all(
        [
            Analysis(user_id=user.id, lot_id="one", title="Own", result_json={}),
            Analysis(user_id=other.id, lot_id="two", title="Private", result_json={}),
        ]
    )
    await session.flush()
    with pytest.raises(HTTPException) as error:
        await lots.compare_lots(
            lots.CompareLotsRequest(lot_ids=["one", "two"]), user.web_client_id, session
        )
    assert error.value.status_code == 404
    session.add(
        Analysis(user_id=user.id, lot_id="three", title="Own other", budget_kzt=500, result_json={})
    )
    await session.flush()
    result = await lots.compare_lots(
        lots.CompareLotsRequest(lot_ids=["one", "three"]), user.web_client_id, session
    )
    assert [row["title"] for row in result["items"]] == ["Own", "Own other"]
    assert (await repo.get_user_quota(session, user.id))["used"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("price,accepted", [(1000000, False), (500000, True)])
async def test_checkout_checks_actual_provider_price_before_charge(
    session, monkeypatch, price, accepted
):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "local-fixture")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "local-fixture")
    monkeypatch.setattr(settings, "stripe_price_plus", "price_fixture")
    client = SimpleNamespace(
        get=AsyncMock(
            return_value=httpx.Response(
                200,
                request=httpx.Request("GET", "https://api.stripe.com/v1/prices/price_fixture"),
                json={
                    "currency": "kzt",
                    "unit_amount": price,
                    "active": True,
                    "recurring": {"interval": "month", "interval_count": 1},
                },
            )
        ),
        post=AsyncMock(
            return_value=httpx.Response(
                200,
                request=httpx.Request("POST", "https://api.stripe.com/v1/checkout/sessions"),
                json={"id": "cs_fixture", "url": "https://checkout.stripe.com/c/pay/fixture"},
            )
        ),
    )

    class Context:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(account.httpx, "AsyncClient", lambda **kwargs: Context())
    args = dict(
        payload=account.CheckoutRequest(plan="plus"),
        auth_user=SupabaseUser(id="11111111-1111-4111-8111-111111111111", email=None),
        session=session,
    )
    if accepted:
        result = await account.create_billing_checkout(**args)
        assert result["checkout_url"].startswith("https://checkout.stripe.com/")
        assert client.post.await_count == 1
    else:
        with pytest.raises(HTTPException) as error:
            await account.create_billing_checkout(**args)
        assert error.value.detail == "BILLING_PRICE_MISMATCH"
        assert client.post.await_count == 0
