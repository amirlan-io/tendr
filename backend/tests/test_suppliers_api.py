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
    # Валидное тело: иначе FastAPI отвечает 422 на этапе валидации тела,
    # не доходя до проверки авторизации.
    body = {
        "/api/suppliers/search": {"lot_id": "1", "requirements": []},
        "/api/suppliers/feedback": {"candidate_id": 1, "verdict": "fits"},
        "/api/suppliers/draft": {"candidate_id": 1, "kind": "email"},
        "/api/tenders/feedback": {"lot_id": "1", "verdict": "fits"},
        "/api/outreach/email": {"approval_id": 1, "subject": "тема"},
        "/api/outreach/call": {"approval_id": 1},
    }
    resp = await anon_client.request(method, path, json=body.get(path, {}))
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


# ── Реальная схема Documenter (name/value/is_critical) ────────────────


def test_requirements_parser_handles_real_documenter_schema() -> None:
    """Documenter отдаёт name/value/is_critical, а не title/description.

    На живом тендере пустые заголовки означали бы, что агент сверяет
    поставщиков с пустым списком — поэтому схема зафиксирована тестом.
    """
    from app.api.suppliers import _requirement_lines, _requirements_from_analysis

    class FakeAnalysis:
        result_json = {
            "lot": {
                "requirements": [
                    {
                        "name": "Вал карданный",
                        "value": "Требуется 1 шт. вала карданного.",
                        "is_critical": True,
                        "category": "",
                    },
                    {
                        "name": "Фильтр тонкой очистки",
                        "value": "Требуется 1 шт. фильтра масла.",
                        "is_critical": True,
                    },
                ]
            }
        }

    reqs = _requirements_from_analysis(FakeAnalysis())
    assert len(reqs) == 2
    assert reqs[0]["title"] == "Вал карданный"
    assert "вала карданного" in reqs[0]["description"]
    assert reqs[0]["is_mandatory"] is True
    assert reqs[0]["code"]

    lines = _requirement_lines(reqs)
    assert any("Вал карданный" in line for line in lines)
    assert any("[обязательный]" in line for line in lines)


def test_requirements_parser_handles_legacy_title_schema() -> None:
    from app.api.suppliers import _requirements_from_analysis

    class FakeAnalysis:
        result_json = {
            "lot": {
                "requirements": [
                    {"title": "Сталь 304", "description": "нержавеющая", "is_mandatory": True},
                    {"title": "Покрытие"},  # без description
                    {"name": ""},  # пустое — пропустить
                ]
            }
        }

    reqs = _requirements_from_analysis(FakeAnalysis())
    assert [r["title"] for r in reqs] == ["Сталь 304", "Покрытие"]


def test_supplier_agent_is_instantiable() -> None:
    """Agent — ABC: без run() агент нельзя создать.

    На живом прогоне это дало 500 «Can't instantiate abstract class».
    """
    from app.agents.supplier_agent import Requirement, SupplierAgent

    agent = SupplierAgent()
    assert callable(agent.run)
    assert hasattr(agent, "find_suppliers")
    assert agent.name == "supplier_agent"
    assert Requirement(code="1", title="Фильтр").is_mandatory is False


@pytest.mark.asyncio
async def test_outreach_agent_is_instantiable() -> None:
    """Та же проверка для OutreachAgent: он тоже наследует Agent."""
    from app.agents.outreach_agent import CompanyContacts, OutreachAgent

    agent = OutreachAgent()
    agent._chat_json = _fake_email_chat  # type: ignore[method-assign]

    # run() маршрутизирует в нужный метод и не отправляет ничего.
    out = await agent.run(
        kind="email",
        supplier_name="ТОО Тест",
        lot_title="Вал карданный",
        requirements=["Вал карданный"],
        contacts=CompanyContacts(company_name="ТОО Проверка"),
    )
    assert "email" in out
    assert out["email"]["ok"] is True


@pytest.mark.asyncio
async def test_outreach_agent_run_call_plan() -> None:
    from app.agents.outreach_agent import CompanyContacts, OutreachAgent

    agent = OutreachAgent()
    agent._chat_json = _fake_call_chat  # type: ignore[method-assign]
    out = await agent.run(
        kind="call",
        supplier_name="ТОО Тест",
        lot_title="Вал карданный",
        requirements=["Вал карданный"],
        contacts=CompanyContacts(company_name="ТОО Проверка"),
    )
    assert "call_plan" in out
    plan = out["call_plan"]
    # Красные линии дополняются запретом на обязательства (F6).
    assert any("Не соглашаться на цену" in line for line in plan["red_lines"])
    # AI представляется и называет компанию.
    assert "Проверка" in plan["introduction"]


async def _fake_email_chat(*_args, **_kwargs):
    return {
        "email": {
            "subject": "Запрос по закупке",
            "body": "Здравствуйте! Интересует поставка. Цена и наличие?",
        }
    }


async def _fake_call_chat(*_args, **_kwargs):
    return {
        "call_plan": {
            "goal": "Уточнить цену и наличие",
            "questions": ["Какова цена за единицу?"],
            "red_lines": [],
            "exit_script": "Спасибо, перезвоним.",
            "introduction": "",
        }
    }


@pytest.mark.asyncio
async def test_match_requirements_returns_costs() -> None:
    """Функция обязана возвращать Costs, а не None.

    Без return в конце поиск падал на реальном прогоне:
    «'NoneType' object has no attribute 'llm_usd'».
    """
    from app.agents.supplier_agent import Costs, Requirement, SupplierCandidate, SupplierAgent

    agent = SupplierAgent()
    agent._chat_json = _fake_chat  # type: ignore[method-assign]
    candidate = SupplierCandidate(
        supplier="ТОО Тест", domain="test.kz", title="Вал карданный", url="https://test.kz/x"
    )
    costs = await agent.match_requirements(
        [candidate], [Requirement(code="1", title="Вал карданный", is_mandatory=True)]
    )
    assert isinstance(costs, Costs)
    assert costs.llm_usd > 0
    # Пункт, о котором LLM не сказал, честно помечен как «нет данных».
    assert candidate.requirement_matches[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_match_requirements_empty_shortcut() -> None:
    from app.agents.supplier_agent import Costs, SupplierCandidate, SupplierAgent

    agent = SupplierAgent()
    candidate = SupplierCandidate(supplier="X", domain="x.kz", title="T")
    costs = await agent.match_requirements([candidate], [])
    assert isinstance(costs, Costs)


async def _fake_chat(*_args, **_kwargs):
    return {"requirement_matches": []}


def test_requirements_parser_skips_empty_results() -> None:
    from app.api.suppliers import _requirements_from_analysis

    assert _requirements_from_analysis(None) == []

    class NoLot:
        result_json = {}

    assert _requirements_from_analysis(NoLot()) == []


@pytest.mark.asyncio
async def test_push_history_persists_full_result_as_json() -> None:
    """result_json должен пережить JSON-сериализацию.

    Реальный прогон на тендере упал с «Object of type datetime is not
    JSON serializable»: в полном результате есть datetime, который JSONB
    не принимает. Проверяем, что datetime приводится к ISO-строке.
    """
    import json
    from datetime import datetime

    from app.db import supplier_repo  # noqa: F401  (проверка импорта репо)
    from app.db import Base
    from app.db import repo as db_repo
    from app.db.models import User
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        user = User(web_client_id="jsoncheck_user_000001")
        session.add(user)
        await session.flush()

        row = await db_repo.push_history(
            session,
            user.id,
            {
                "lot_id": "777",
                "title": "Лот",
                "url": "https://v3bl.goszakup.gov.kz/ru/announce/index/777-1",
                "overall_risk": "low",
                "n_requirements": 1,
                "n_red_flags": 0,
                "result_json": {
                    "lot": {
                        "lot_id": "777",
                        "title": "Лот",
                        "requirements": [{"name": "Фильтр", "value": "1 шт."}],
                    },
                    "created_at": datetime(2026, 1, 1, 12, 0, 0),
                },
            },
        )
        assert row is not None
        # Сериализуется без исключения — значит, datetime уже приведён.
        # ensure_ascii=False, иначе кириллица экранируется и проверка врёт.
        dumped = json.dumps(row.result_json, ensure_ascii=False, default=str)
        assert "Фильтр" in dumped
        assert "2026-01-01T12:00:00" in dumped
        # И требования читаются обратно агентом.
        from app.api.suppliers import _requirements_from_analysis

        assert _requirements_from_analysis(row)[0]["title"] == "Фильтр"

    await engine.dispose()