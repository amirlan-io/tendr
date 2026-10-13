"""Regression tests for the twelve agreed audit fixes, without external expenditure."""
import io
import sys
from pathlib import Path
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import Request
from docx import Document
from qdrant_client import QdrantClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db import Base, get_db, repo
from app.db.models import User, Analysis, Lot, B2GWorkspace, AnalysisJob, SupplierCandidate, ApprovalQueue
from app.main import create_app
from app.core.config import get_settings
from app.core.supabase_auth import SupabaseUser, require_supabase_user
from app.api import b2g, lots, products
from app.api.account import admin_reset_quota, ResetQuotaRequest
from app.schemas.lot import B2GResult, LotSearchResult, ProductSearchResult, ApplicationRequest
from app.services.outreach import OutreachService, OutreachNotAllowed
from app.agents.outreach_agent import CompanyContacts
from app.agents.application_generator import generate_application_docx
from app.services import analysis_jobs
from app.rag.store import RAGStore
from app.rag.indexer import index_path
from app.llm.base import EmbeddingResponse

WEB_ID = "supabase_11111111111141118111111111111111"
AUTH = SupabaseUser(id="11111111-1111-4111-8111-111111111111", email=None)

@pytest_asyncio.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import app.db
    monkeypatch.setattr(app.db, "SessionLocal", factory)
    monkeypatch.setattr(analysis_jobs, "SessionLocal", factory)
    async with factory() as session:
        user = User(web_client_id=WEB_ID)
        session.add(user)
        await session.commit()
        yield session, factory, user
    await engine.dispose()

@pytest_asyncio.fixture
async def client(database, monkeypatch):
    _, factory, _ = database
    app = create_app(test_mode=True)
    from app.core import supabase_auth, client_id
    async def optional(request):
        return AUTH if request.headers.get("Authorization") == "Bearer local-test" else None
    monkeypatch.setattr(supabase_auth, "get_optional_supabase_user", optional)
    monkeypatch.setattr(client_id, "get_optional_supabase_user", optional)
    app.dependency_overrides[require_supabase_user] = lambda: AUTH
    async def db():
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except BaseException:
                await s.rollback()
                raise
    app.dependency_overrides[get_db] = db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://localhost", headers={"Authorization":"Bearer local-test"}) as c:
        yield c

@pytest.mark.asyncio
async def test_b2g_only_uses_public_catalog(database, monkeypatch):
    s, _, user = database
    other = User(web_client_id="supabase_other_private_user"); s.add(other); await s.flush()
    s.add(Analysis(user_id=other.id, lot_id="private", title="Стулья секретной компании", budget_kzt=100, result_json={}))
    s.add(Lot(source="goszakup", source_id="123", title="Стулья из публичного каталога", amount_kzt=500, organizer="Публичный заказчик"))
    ws = B2GWorkspace(owner_id=user.id, name="Workspace"); s.add(ws); await s.commit()
    captured = []
    async def generate(req, **kwargs):
        captured.extend(req.similar_lots)
        return B2GResult(title="Draft")
    monkeypatch.setattr(b2g, "_user_for_request", AsyncMock(return_value=user))
    monkeypatch.setattr(b2g, "B2GAgent", lambda: SimpleNamespace(run=generate))
    await b2g.generate_tz.__wrapped__(ws.id, b2g.CreateTzRequest(need_description="Стулья"), Request({"type":"http","headers":[]}), s)
    assert [r["title"] for r in captured] == ["Стулья из публичного каталога"]

@pytest.mark.asyncio
async def test_ai_search_requires_auth_and_confirms_actual_credits(client, database, monkeypatch):
    s, _, user = database
    monkeypatch.setattr(lots, "_run_lot_search", AsyncMock(return_value=LotSearchResult(lots=[], total=0, source="test", ai_credits_used=1)))
    response = await client.post("/api/lots/search", headers={"X-Client-Id":"test_guest_123456789"}, json={"with_ai":True,"ai_limit":3})
    assert response.status_code == 200
    assert (await repo.get_user_quota(s, user.id))["used"] == 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(test_mode=True)), base_url="http://localhost") as anon:
        denied = await anon.post("/api/lots/search", headers={"X-Client-Id":"test_guest_123456789"}, json={"with_ai":True,"ai_limit":1})
        assert denied.status_code == 401

@pytest.mark.asyncio
async def test_common_ledger_prevents_unlimited_product_search(client, database, monkeypatch):
    s, _, user = database
    run = AsyncMock(return_value=ProductSearchResult(query="test", products=[]))
    monkeypatch.setattr(products, "ProductSearchAgent", lambda: SimpleNamespace(run=run))
    for _ in range(3):
        assert (await client.post("/api/products/search", json={"query":"test"})).status_code == 200
    assert (await client.post("/api/products/search", json={"query":"test"})).status_code == 429
    assert run.await_count == 3
    assert (await repo.get_user_quota(s, user.id))["used"] == 3

@pytest.mark.asyncio
async def test_provider_failure_returns_credit(client, database, monkeypatch):
    s, _, user = database
    monkeypatch.setattr(products, "ProductSearchAgent", lambda: SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("offline"))))
    assert (await client.post("/api/products/search", json={"query":"test"})).status_code == 500
    assert (await repo.get_user_quota(s, user.id))["remaining"] == 3

@pytest.mark.asyncio
async def test_outreach_is_dispatched_once(database):
    s, _, user = database
    candidate = SupplierCandidate(user_id=user.id, lot_id="1", supplier="Test", card_json={"email":"nobody@example.test"})
    s.add(candidate); await s.flush()
    approval = ApprovalQueue(user_id=user.id, candidate_id=candidate.id, kind="email", status="approved", draft_text="Здравствуйте. Просим сообщить цену.")
    s.add(approval); await s.commit()
    provider = SimpleNamespace(send=AsyncMock(return_value={"status":"sent","id":"local-fake"}))
    service = OutreachService(email_provider=provider)
    await service.send_approved_email(s, user_id=user.id, approval_id=approval.id, subject="Test", contacts=CompanyContacts())
    await s.commit()
    with pytest.raises(OutreachNotAllowed, match="APPROVAL_ALREADY_EXECUTED"):
        await service.send_approved_email(s, user_id=user.id, approval_id=approval.id, subject="Test", contacts=CompanyContacts())
    assert provider.send.await_count == 1

def test_docx_vat_is_extracted_from_gross_price():
    content = generate_application_docx(ApplicationRequest(supplier_name="Test", proposed_price_kzt=112000, vat_rate=12), None)
    text = "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
    assert "12,000.00 тенге" in text
    assert "13,440" not in text

@pytest.mark.asyncio
async def test_recovery_does_not_reset_a_live_worker(database, monkeypatch):
    s, _, user = database
    job = AnalysisJob(id="a"*32, user_id=user.id, kind="url", status="running", lease_owner="worker", lease_until=datetime.now(UTC).replace(tzinfo=None)+timedelta(seconds=120), input_json={})
    s.add(job); await s.commit()
    enqueue = AsyncMock(); monkeypatch.setattr(analysis_jobs, "schedule_analysis_job", enqueue)
    await analysis_jobs.recover_analysis_jobs()
    await s.refresh(job)
    assert job.status == "running"
    enqueue.assert_not_awaited()
    job.lease_until = datetime.now(UTC).replace(tzinfo=None)-timedelta(seconds=1); await s.commit()
    await analysis_jobs.recover_analysis_jobs()
    await s.refresh(job)
    assert job.status == "queued"
    enqueue.assert_awaited_once_with(job.id)

@pytest.mark.asyncio
async def test_reset_keeps_history_and_records_adjustment(database):
    s, _, user = database
    s.add(Analysis(user_id=user.id, lot_id="1", title="Saved report", result_json={}))
    reservation = await repo.reserve_user_quota(s, user.id, operation_key="test")
    await repo.confirm_user_quota(s, user.id, reservation_key=reservation["reservation_key"])
    await s.commit()
    await admin_reset_quota(ResetQuotaRequest(web_client_id=WEB_ID, reason="Test adjustment"), session=s)
    await s.commit()
    assert await s.scalar(select(func.count(Analysis.id))) == 1
    assert (await repo.get_user_quota(s, user.id))["used"] == 0

@pytest.mark.asyncio
async def test_corpus_switch_removes_obsolete_chunks_and_keeps_old_version(tmp_path, monkeypatch):
    client = QdrantClient(location=":memory:")
    class Embedder:
        dim = 2
        async def embed_batch(self, texts): return [EmbeddingResponse([1.,0.], "fake") for _ in texts]
    monkeypatch.setattr(RAGStore, "_get_client", lambda self: client)
    monkeypatch.setattr(RAGStore, "_get_embedder", lambda self: Embedder())
    path = tmp_path / "law.txt"; path.write_text("Старый пункт закона. " * 150)
    await index_path(tmp_path, "test_corpus")
    first = client.get_aliases().aliases[0].collection_name
    path.write_text("Новая редакция закона.")
    await index_path(tmp_path, "test_corpus")
    second = client.get_aliases().aliases[0].collection_name
    assert first != second
    assert client.collection_exists(first)
    points, _ = client.scroll("test_corpus_active", with_payload=True)
    assert len(points) == 1 and points[0].payload["text"] == "Новая редакция закона."
    client.close()

@pytest.mark.asyncio
async def test_bot_linking_and_signed_requests_share_web_identity(database, monkeypatch):
    s, _, user = database
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bot"))
    from bot.http_client import BotApiClient
    from bot import http_client
    monkeypatch.setattr(get_settings(), "bot_api_secret", "x" * 40)
    monkeypatch.setattr(http_client, "get_settings", lambda: SimpleNamespace(bot_api_secret="x" * 40))
    app = create_app(test_mode=True)
    async def db(): yield s
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[require_supabase_user] = lambda: AUTH
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as web:
        token = (await web.post("/api/account/telegram/link-token")).json()["command"].split()[1]
    app.dependency_overrides.pop(require_supabase_user)
    async with BotApiClient(telegram_id=101, transport=transport) as bot:
        linked = await bot.post("http://localhost/account/telegram/link", json={"code":token})
        assert linked.status_code == 200
        assert (await bot.get("http://localhost/account/quota")).json()["user_id"] == user.id
        assert (await bot.post("http://localhost/account/telegram/link", json={"code":token})).status_code == 400
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as spoof:
        assert (await spoof.get("/api/account/quota", headers={"X-Telegram-Id":"101"})).status_code == 401

def test_required_sdk_adapters_import():
    from tavily import TavilyClient
    from browser_use_sdk.v3 import AsyncBrowserUse
    assert TavilyClient is not None and AsyncBrowserUse is not None

@pytest.mark.asyncio
async def test_ai_search_zero_and_failure_release_credits(client, database, monkeypatch):
    s, _, user = database
    monkeypatch.setattr(lots, "_run_lot_search", AsyncMock(return_value=LotSearchResult(lots=[], total=0, source="test", ai_credits_used=0)))
    assert (await client.post("/api/lots/search", json={"with_ai":True,"ai_limit":3})).status_code == 200
    assert (await repo.get_user_quota(s, user.id))["used"] == 0
    monkeypatch.setattr(lots, "_run_lot_search", AsyncMock(side_effect=RuntimeError("provider down")))
    assert (await client.post("/api/lots/search", json={"with_ai":True,"ai_limit":3})).status_code == 500
    assert (await repo.get_user_quota(s, user.id))["used"] == 0

@pytest.mark.asyncio
async def test_failed_reindex_does_not_promote_partial_corpus(tmp_path, monkeypatch):
    client = QdrantClient(location=":memory:")
    class Embedder:
        dim = 2
        async def embed_batch(self, texts): return [EmbeddingResponse([1.,0.], "fake") for _ in texts]
    monkeypatch.setattr(RAGStore, "_get_client", lambda self: client)
    monkeypatch.setattr(RAGStore, "_get_embedder", lambda self: Embedder())
    path = tmp_path / "law.txt"; path.write_text("Действующая редакция.")
    await index_path(tmp_path, "law_test")
    active = client.get_aliases().aliases[0].collection_name
    path.write_text("Неполная новая редакция.")
    monkeypatch.setattr(RAGStore, "upsert", AsyncMock(return_value=0))
    with pytest.raises(RuntimeError, match="Incomplete corpus"):
        await index_path(tmp_path, "law_test")
    assert client.get_aliases().aliases[0].collection_name == active
    client.close()

@pytest.mark.asyncio
async def test_browser_sdk_receives_enforced_budget(monkeypatch):
    from app.agents.browser_use.client import BrowserUseAgent
    monkeypatch.setattr(get_settings(), "browser_use_max_cost_usd", 0.25)
    fake = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(id="fake-session", status="completed", output="ok")))
    agent = BrowserUseAgent(api_key="local-fixture")
    monkeypatch.setattr(agent, "_get_client", AsyncMock(return_value=fake))
    await agent.run_task("Read public lot", enable_recording=False)
    assert fake.run.call_args.kwargs["max_cost_usd"] == 0.25
    await agent.continue_session("fake-session", "Continue")
    assert fake.run.call_args.kwargs["max_cost_usd"] == 0.25
