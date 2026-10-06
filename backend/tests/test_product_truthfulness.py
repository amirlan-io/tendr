from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.account import (
    _activate_stripe_subscription,
    _deactivate_stripe_subscription,
    _stripe_period,
    _verify_stripe_signature,
)
from app.db import Base, repo
from app.db.models import Analysis, QuotaReservation, Subscription, User
from app.schemas.lot import LotAnalysis, LotCreate
from app.services.goszakup_parser import ParsedLot
from app.services.orchestrator import LotOrchestrator
from app.services.outreach import LeximoCallProvider, outreach_capabilities
from app.services.scoring import estimate_margin_pct, get_customer_score


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


def test_unknown_legal_risk_never_becomes_participate() -> None:
    assert LotOrchestrator._make_recommendation(risk="needs_review", trust=95, margin_pct=40) == "review"


@pytest.mark.asyncio
async def test_quick_analysis_keeps_original_lot_url() -> None:
    """Регрессия: быстрый разбор не должен падать при добавлении source_url."""
    source_url = "https://v3bl.goszakup.gov.kz/ru/announce/index/17686160-1"
    parsed = ParsedLot(
        lot_id="17686160",
        title="Работы по изготовлению мебели",
        customer_name="Тестовый заказчик",
        customer_bin="123456789012",
        method="tender",
        deadline="2026-11-01T12:00:00",
        budget_kzt=1_000_000,
        description="Изготовление мебели по технической спецификации.",
        technical_specification="Изготовить комплект мебели по указанным размерам. " * 8,
        extra={"source_url": source_url},
    )
    orchestrator = LotOrchestrator()
    orchestrator._resolve_lot = AsyncMock(return_value=parsed)
    orchestrator._documenter.run = AsyncMock(
        return_value=LotAnalysis(
            lot_id=parsed.lot_id,
            title="(не удалось проанализировать)",
        )
    )

    result = await orchestrator.analyze_lot(
        LotCreate(source_url=source_url, source_id="17686160-1"),
        user_id=1,
        is_pilot=False,
        used_this_month=0,
        free_limit=3,
        with_legal=False,
    )

    assert result.lot.source_url == source_url
    assert result.lot.title == parsed.title
    assert result.lot.customer == parsed.customer_name
    assert result.lot.requirements[0].name == "Техническая спецификация"
    assert "официального лота" in result.lot.warnings[0]


def test_margin_is_explicitly_an_estimate() -> None:
    estimate = estimate_margin_pct("Поставка компьютеров")
    assert estimate["is_estimate"] is True
    assert estimate["method"] == "category_baseline"
    assert "не расчёт" in estimate["disclaimer"]
    assert estimate["assumptions"]


@pytest.mark.asyncio
async def test_customer_score_discloses_internal_evidence(session) -> None:
    user = User(web_client_id="truthfulness_customer_001")
    session.add(user)
    await session.flush()
    session.add(
        Analysis(
            user_id=user.id,
            lot_id="1",
            customer="ТОО Проверка",
            result_json={},
            overall_risk="low",
        )
    )
    await session.flush()
    score = await get_customer_score(session, "ТОО Проверка")
    assert score["is_estimate"] is True
    assert score["method"] == "internal_analyses"
    assert score["evidence_count"] == 1
    assert "не подтверждает" in score["disclaimer"]


@pytest.mark.asyncio
async def test_five_hour_limit_is_enforced_for_paid_plan(session) -> None:
    now = datetime.now(timezone.utc)
    user = User(web_client_id="rolling_window_user_001", is_subscribed=True)
    session.add(user)
    await session.flush()
    session.add(
        Subscription(
            user_id=user.id,
            plan="plus",
            monthly_limit=150,
            is_active=True,
            starts_at=(now - timedelta(days=1)).replace(tzinfo=None),
            expires_at=(now + timedelta(days=20)).replace(tzinfo=None),
        )
    )
    for index in range(20):
        session.add(
            Analysis(
                user_id=user.id,
                lot_id=f"window-{index}",
                result_json={},
                created_at=(now - timedelta(minutes=30)).replace(tzinfo=None),
            )
        )
    await session.flush()
    quota = await repo.get_user_quota(session, user.id, now_override=now)
    assert quota["plan"] == "plus"
    assert quota["window_limit"] == 20
    assert quota["remaining_last_5_hours"] == 0
    with pytest.raises(repo.QuotaLimitExceeded, match="Five-hour"):
        await repo.reserve_user_quota(
            session,
            user.id,
            operation_key="blocked-by-window",
            now_override=now,
        )


@pytest.mark.asyncio
async def test_repeated_analysis_of_same_lot_still_consumes_each_credit(session) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user = User(web_client_id="repeated_lot_quota_001")
    session.add(user)
    await session.flush()
    session.add(Analysis(user_id=user.id, lot_id="same-lot", result_json={}, created_at=now))
    for index in range(2):
        session.add(
            QuotaReservation(
                user_id=user.id,
                reservation_key=f"confirmed-{index}",
                operation_key=f"same-lot-{index}",
                amount=1,
                month_key=now.strftime("%Y-%m"),
                status="confirmed",
                reserved_at=now,
                expires_at=now + timedelta(minutes=5),
                confirmed_at=now,
            )
        )
    await session.flush()
    quota = await repo.get_user_quota(session, user.id, now_override=now)
    assert quota["used_this_month"] == 2
    assert quota["used_last_5_hours"] == 2


def test_stripe_signature_verification() -> None:
    secret = "whsec_test"
    payload = json.dumps({"type": "checkout.session.completed"}).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    assert _verify_stripe_signature(payload, f"t={timestamp},v1={signature}", secret)
    assert not _verify_stripe_signature(payload + b"x", f"t={timestamp},v1={signature}", secret)


def test_stripe_period_supports_current_item_shape() -> None:
    now = datetime(2026, 1, 1)
    start = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
    starts_at, expires_at = _stripe_period(
        {"items": {"data": [{"current_period_start": start, "current_period_end": end}]}},
        now=now,
    )
    assert starts_at == datetime(2026, 2, 1)
    assert expires_at == datetime(2026, 3, 1)


@pytest.mark.asyncio
async def test_stripe_subscription_can_be_activated_and_cancelled(session) -> None:
    user = User(web_client_id="stripe_lifecycle_001")
    session.add(user)
    await session.flush()
    await _activate_stripe_subscription(
        session,
        user=user,
        plan="pro",
        external_id="sub_test_1",
        starts_at=datetime(2026, 2, 1),
        expires_at=datetime(2026, 3, 1),
    )
    await session.flush()
    assert user.is_subscribed is True
    assert user.subscription_expires_at == datetime(2026, 3, 1)
    await _deactivate_stripe_subscription(session, external_id="sub_test_1")
    await session.flush()
    assert user.is_subscribed is False
    assert user.subscription_expires_at is None


def test_outreach_capabilities_never_claim_unconfigured_providers(monkeypatch) -> None:
    from app.services import outreach

    monkeypatch.setattr(
        outreach,
        "get_settings",
        lambda: SimpleNamespace(
            smtp_host="", smtp_from_email="", leximo_api_token="", leximo_agent_id=""
        ),
    )
    capabilities = outreach_capabilities()
    assert capabilities["email"]["available"] is False
    assert capabilities["call"]["available"] is False
    assert capabilities["requires_approval"] is True


@pytest.mark.asyncio
async def test_leximo_adapter_uses_official_assignment_contract(monkeypatch) -> None:
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "assignment-1"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return Response()

    monkeypatch.setattr("app.services.outreach.httpx.AsyncClient", lambda **_: Client())
    provider = LeximoCallProvider(api_token="token", agent_id="agent-1")
    result = await provider.place_call(
        to_phone="+77000000000",
        scenario={"goal": "Уточнить наличие", "questions": ["Цена?"]},
        metadata={"supplier": "ТОО Поставщик"},
    )
    assert captured["url"] == "https://concierge.leximo.ai/api/assignment"
    assert captured["json"]["agentId"] == "agent-1"
    assert captured["json"]["phoneNumber"] == "+77000000000"
    assert result["id"] == "assignment-1"

