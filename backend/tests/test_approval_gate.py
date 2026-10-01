"""Интеграционные тесты гейта одобрения (ТЗ §10: «Без approval — ноль исходящих»).

Проверяем на реальной БД (SQLite в памяти) и настоящих сервисах:
* send_approved_email / place_approved_call отказывают для pending/rejected;
* после approved действие проходит (на stub-провайдерах);
* стоп-лист поставщика блокирует исходящее даже после одобрения;
* режим manual блокирует отправку;
* письмо без адресата не уходит.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.outreach_agent import CompanyContacts
from app.db import Base
from app.db import supplier_repo as srepo
from app.services.outreach import (
    OutreachNotAllowed,
    OutreachService,
    SendResult,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


class StubEmail:
    """Провайдер писем: записывает вызовы, чтобы проверить гейт."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, *, to_email, subject, body, reply_to):
        self.calls.append(
            {"to": to_email, "subject": subject, "body": body, "reply_to": reply_to}
        )
        return {"status": "sent", "id": "stub-1", "cost_usd": 0.0}


class StubCall:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def place_call(self, *, to_phone, scenario, metadata):
        self.calls.append({"to": to_phone, "scenario": scenario, "metadata": metadata})
        return {
            "status": "queued",
            "id": "call-1",
            "cost_usd": 0.5,
            "price_outcome": "countered",
        }


async def _make_user(session):
    from app.db.models import User

    user = User(web_client_id="supabase_test_user_0001")
    session.add(user)
    await session.flush()
    return user


async def _seed(
    session,
    *,
    email: str = "sales@shop.kz",
    phone: str = "+7 727 000 00 00",
    block: bool = False,
):
    user = await _make_user(session)
    rows = await srepo.replace_candidates(
        session,
        user.id,
        "123",
        [
            {
                "supplier": "ТОО Ромашка",
                "domain": "romashka.kz",
                "title": "Фильтр",
                "score": 80,
                "card": {"email": email, "phone": phone},
                "match": {"requirement_matches": [], "warnings": []},
            }
        ],
    )
    candidate = rows[0]
    if block:
        await srepo.add_to_list(
            session, user.id, candidate.supplier, allow=False, reason="не работаем"
        )
    await session.commit()
    return user, candidate


async def _approval(session, user, candidate, kind="email"):
    return await srepo.create_approval(
        session,
        user_id=user.id,
        candidate_id=candidate.id,
        kind=kind,
        draft_text="Здравствуйте, интересует поставка фильтров.",
        plan_json={"introduction": "Здравствуйте, компания X"},
    )


# ── Главный гейт: без approval ноль исходящих ─────────────────────────


@pytest.mark.asyncio
async def test_email_blocked_without_approval(session):
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="email")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(work_email="me@me.kz"),
        )
    assert str(exc.value) == "APPROVAL_REQUIRED"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_call_blocked_without_approval(session):
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="call")
    await session.commit()
    provider = StubCall()
    service = OutreachService(call_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.place_approved_call(
            session, user_id=user.id, approval_id=approval.id
        )
    assert str(exc.value) == "APPROVAL_REQUIRED"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_email_blocked_after_rejection(session):
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="email")
    await srepo.decide_approval(session, user.id, approval.id, decision="rejected")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(),
        )
    assert str(exc.value) == "APPROVAL_REQUIRED"
    assert provider.calls == []


# ── После одобрения действие разрешено ────────────────────────────────


@pytest.mark.asyncio
async def test_email_sends_after_approval(session):
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="email")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    result = await service.send_approved_email(
        session,
        user_id=user.id,
        approval_id=approval.id,
        subject="Тема",
        contacts=CompanyContacts(work_email="me@me.kz"),
    )
    assert isinstance(result, SendResult)
    assert len(provider.calls) == 1
    assert provider.calls[0]["to"] == "sales@shop.kz"


@pytest.mark.asyncio
async def test_call_after_approval_uses_scenario(session):
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="call")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubCall()
    service = OutreachService(call_provider=provider)
    # Среда 12:00 — рабочее время Алматы.
    result = await service.place_approved_call(
        session, user_id=user.id, approval_id=approval.id, now=datetime(2026, 10, 7, 12, 0)
    )
    assert isinstance(result, SendResult)
    assert len(provider.calls) == 1


# ── Дополнительные ограничения ────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_supplier_cannot_be_contacted_even_when_approved(session):
    user, candidate = await _seed(session, block=True)
    approval = await _approval(session, user, candidate, kind="email")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(),
        )
    assert str(exc.value) == "SUPPLIER_BLOCKED"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_manual_mode_blocks_sending_even_when_approved(session):
    user, candidate = await _seed(session)
    profile = await srepo.get_or_create_company_profile(session, user.id)
    profile.outreach_mode = "manual"
    approval = await _approval(session, user, candidate, kind="email")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(),
        )
    assert str(exc.value) == "MANUAL_MODE_BLOCKS_SENDING"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_email_without_recipient_is_not_sent(session):
    user, candidate = await _seed(session, email="")
    approval = await _approval(session, user, candidate, kind="email")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(),
        )
    assert str(exc.value) == "RECIPIENT_EMAIL_MISSING"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_empty_draft_is_not_sent(session):
    user, candidate = await _seed(session)
    approval = await srepo.create_approval(
        session, user_id=user.id, candidate_id=candidate.id, kind="email", draft_text=""
    )
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(),
        )
    assert str(exc.value) == "DRAFT_EMPTY"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_call_blocked_outside_working_hours(session):
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="call")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubCall()
    service = OutreachService(call_provider=provider)
    # Суббота 12:00 — нерабочее время.
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.place_approved_call(
            session, user_id=user.id, approval_id=approval.id, now=datetime(2026, 10, 10, 12, 0)
        )
    assert str(exc.value) == "OUTSIDE_WORKING_HOURS_KZ"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_approved_email_requires_matching_kind(session):
    """Письмо нельзя отправить по заявке на звонок и наоборот."""
    user, candidate = await _seed(session)
    approval = await _approval(session, user, candidate, kind="call")
    await srepo.decide_approval(session, user.id, approval.id, decision="approved")
    await session.commit()
    provider = StubEmail()
    service = OutreachService(email_provider=provider)
    with pytest.raises(OutreachNotAllowed) as exc:
        await service.send_approved_email(
            session,
            user_id=user.id,
            approval_id=approval.id,
            subject="Тема",
            contacts=CompanyContacts(),
        )
    assert str(exc.value) == "APPROVAL_KIND_MISMATCH"
    assert provider.calls == []