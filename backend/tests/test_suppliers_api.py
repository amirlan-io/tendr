"""API-тесты агента поставщиков: авторизация, формат ошибок, безопасность.

Проверяется то, что видит пользователь:
* без валидного Supabase-токена эндпоинты закрыты (401), а не падают;
* ошибки отдаются стабильными кодами, без сырого detail;
* структура ответов совпадает с ожидаемой для фронтенда;
* исходящие действия невозможны без одобрения (через реальный API-слой).
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.supabase_auth import SupabaseUser, require_supabase_user
from app.db import Base, get_db
from app.main import app

TEST_USER_ID = "11111111-2222-3333-4444-555555555555"


def _authed_user() -> SupabaseUser:
    return SupabaseUser(id=TEST_USER_ID, email="tester@example.com")


@pytest_asyncio.fixture
async def client():
    """Async-клиент по ASGI-приложению с тестовой БД в памяти."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[require_supabase_user] = lambda: _authed_user()
    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest_asyncio.fixture
async def anon_client():
    """Клиент без токена — все защищённые ручки должны вернуть 401."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# ── Доступ закрыт без авторизации ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/suppliers/search"),
        ("GET", "/api/suppliers/shortlist?lot_id=1"),
        ("POST", "/api/suppliers/feedback"),
        ("POST", "/api/suppliers/draft"),
        ("GET", "/api/suppliers/price-policy"),
        ("GET", "/api/suppliers/lists"),
        ("GET", "/api/suppliers/profile"),
        ("GET", "/api/tenders/recommended"),
        ("POST", "/api/tenders/feedback"),
        ("GET", "/api/approvals/pending"),
        ("POST", "/api/outreach/email"),
        ("POST", "/api/outreach/call"),
    ],
)
async def test_supplier_endpoints_require_auth(anon_client, method: str, path: str) -> None:
    resp = await anon_client.request(method, path, json={})
    assert resp.status_code == 401, f"{method} {path} должен требовать авторизацию"


# ── Формат ответов для фронтенда ───────────────────────────────────────


@pytest.mark.asyncio
async def test_price_policy_has_default_shape(client) -> None:
    resp = await client.get("/api/suppliers/price-policy")
    assert resp.status_code == 200
    body = resp.json()
    assert "tolerance_pct" in body
    assert "counter_limit_pct" in body
    assert "counter_script" in body


@pytest.mark.asyncio
async def test_company_profile_defaults_to_review_mode(client) -> None:
    resp = await client.get("/api/suppliers/profile")
    assert resp.status_code == 200
    # Безопасный режим по умолчанию: не автоотправка.
    assert resp.json()["outreach_mode"] == "review"


@pytest.mark.asyncio
async def test_company_profile_patch_updates_fields(client) -> None:
    resp = await client.patch(
        "/api/suppliers/profile",
        json={
            "categories": ["фильтры"],
            "regions": ["Астана"],
            "work_email": "boss@company.kz",
            "outreach_mode": "manual",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["categories"] == ["фильтры"]
    assert body["work_email"] == "boss@company.kz"
    assert body["outreach_mode"] == "manual"


@pytest.mark.asyncio
async def test_price_policy_patch_clamps_values(client) -> None:
    resp = await client.patch(
        "/api/suppliers/price-policy", json={"tolerance_pct": 7.5, "counter_limit_pct": 20}
    )
    assert resp.status_code == 200
    assert resp.json()["tolerance_pct"] == 7.5


@pytest.mark.asyncio
async def test_price_policy_counter_limit_not_below_tolerance(client) -> None:
    resp = await client.patch(
        "/api/suppliers/price-policy", json={"tolerance_pct": 20, "counter_limit_pct": 2}
    )
    assert resp.status_code == 200
    body = resp.json()
    # Y не может быть меньше X, иначе зона встречной исчезает.
    assert body["counter_limit_pct"] >= body["tolerance_pct"]


@pytest.mark.asyncio
async def test_blocklist_add_and_list(client) -> None:
    add = await client.post(
        "/api/suppliers/lists", json={"supplier": "ТОО Стоп", "allow": False, "reason": "жалобы"}
    )
    assert add.status_code == 200
    lists = await client.get("/api/suppliers/lists")
    assert lists.status_code == 200
    body = lists.json()
    assert any(item["supplier"] == "ТОО Стоп" for item in body["blocklist"])


@pytest.mark.asyncio
async def test_recommended_returns_explanation_shape(client) -> None:
    resp = await client.get("/api/tenders/recommended")
    assert resp.status_code == 200
    body = resp.json()
    # Даже без лотов структура объяснения должна быть стабильной.
    assert "items" in body
    assert "cold_start" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_interests_roundtrip(client) -> None:
    patch = await client.patch(
        "/api/profile/interests",
        json={"categories": ["фильтры"], "regions": ["Астана"], "quiz_completed": True},
    )
    assert patch.status_code == 200
    got = await client.get("/api/profile/interests")
    assert got.status_code == 200
    assert got.json()["quiz_completed"] is True


@pytest.mark.asyncio
async def test_digest_settings_limit_rejected_above_max(client) -> None:
    """Слишком большой лимит отвергается валидацией, а не молча обрезается."""
    resp = await client.patch("/api/digest/settings", json={"daily_limit": 999})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_digest_settings_roundtrip(client) -> None:
    resp = await client.patch("/api/digest/settings", json={"daily_limit": 7, "hour_kz": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["daily_limit"] == 7
    assert body["hour_kz"] == 10
    assert "next_send_at" in body


# ── Гейт одобрения через API ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_outreach_email_blocked_without_approval(client) -> None:
    """Даже с валидной авторизацией без одобрения отправка невозможна."""
    resp = await client.post(
        "/api/outreach/email", json={"approval_id": 999999, "subject": "тема"}
    )
    assert resp.status_code in {403, 404}
    assert resp.json()["detail"] in {"APPROVAL_NOT_FOUND", "APPROVAL_REQUIRED"}


@pytest.mark.asyncio
async def test_outreach_call_blocked_without_approval(client) -> None:
    resp = await client.post("/api/outreach/call", json={"approval_id": 999999})
    assert resp.status_code in {403, 404}
    assert resp.json()["detail"] in {"APPROVAL_NOT_FOUND", "APPROVAL_REQUIRED"}


@pytest.mark.asyncio
async def test_approval_decision_unknown_id_is_404(client) -> None:
    resp = await client.post(
        "/api/approvals", json={"approval_id": 999999, "decision": "approved"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "APPROVAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_search_without_requirements_returns_400(client) -> None:
    """Пустой список требований — честный отказ, а не выдуманный поиск."""
    resp = await client.post(
        "/api/suppliers/search", json={"lot_id": "123", "requirements": []}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "REQUIREMENTS_REQUIRED"


@pytest.mark.asyncio
async def test_cost_summary_shape(client) -> None:
    resp = await client.get("/api/outreach/audit/costs")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("llm_usd", "tavily_usd", "browser_usd", "call_usd", "total_usd"):
        assert key in body


@pytest.mark.asyncio
async def test_audit_log_shape(client) -> None:
    resp = await client.get("/api/audit?limit=5")
    assert resp.status_code == 200
    assert "items" in resp.json()