from __future__ import annotations

import inspect
import io
import os
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.api import admin as admin_api, browser_actions, lots as lots_api
from app.core.client_id import generate_client_id, require_client_id, validate_client_id
from app.db import Base
from app.db import repo as db_repo
from app.db.models import User
from app.main import app
from app.services.goszakup_parser import GoszakupParser

client = TestClient(app)


def test_extract_reference_rejects_untrusted_host() -> None:
    with pytest.raises(ValueError):
        GoszakupParser._normalize_reference("https://evil.example/ru/announce/index/17266377")


def test_goszakup_reference_kind_and_http_restriction() -> None:
    lot_ref = GoszakupParser.parse_reference("https://v3bl.goszakup.gov.kz/ru/announce/index/17549503-1")
    assert lot_ref.kind.value == "lot_number"
    assert lot_ref.lot_number == "17549503-1"
    assert lot_ref.announcement_id is None
    assert lot_ref.announcement_number is None

    with pytest.raises(ValueError):
        GoszakupParser.parse_reference("http://goszakup.gov.kz/ru/announce/index/17549503-1")


def test_extract_reference_keeps_lot_number_suffix_and_enforces_strict_host() -> None:
    ref = GoszakupParser._normalize_reference("https://v3bl.goszakup.gov.kz/ru/announce/index/17549503-1")
    assert ref == "17549503-1"

    parsed = GoszakupParser.parse_reference("https://v3bl.goszakup.gov.kz/ru/announce/index/17549503-1")
    assert parsed.kind.value == "lot_number"
    assert parsed.lot_number == "17549503-1"
    assert parsed.announcement_id is None
    assert parsed.announcement_number is None
    assert parsed.source_url.endswith("/17549503-1")

    with pytest.raises(ValueError):
        GoszakupParser._normalize_reference("https://evil.example/ru/announce/index/17549503-1")
    with pytest.raises(ValueError):
        GoszakupParser._normalize_reference("https://goszakup.gov.kz:8443/ru/announce/index/17549503-1")


def test_goszakup_reference_rejects_userinfo_fragment_http_and_lookalike_hosts() -> None:
    invalid_values = [
        "https://user:pass@v3bl.goszakup.gov.kz/ru/announce/index/17549503-1",
        "https://goszakup.gov.kz/ru/announce/index/17549503-1#fragment",
        "ftp://goszakup.gov.kz/ru/announce/index/17549503-1",
        "https://localhost/ru/announce/index/17549503-1",
        "https://127.0.0.1/ru/announce/index/17549503-1",
        "https://10.0.0.1/ru/announce/index/17549503-1",
        "https://goszakup.gov.kz.evil.example/ru/announce/index/17549503-1",
        "https://goszakup.gov.kz/ru/search?q=17549503-1",
        "https://goszakup.gov.kz/unknown/path/17549503-1",
    ]
    for value in invalid_values:
        with pytest.raises(ValueError):
            GoszakupParser.parse_reference(value)


def test_admin_placeholder_key_is_rejected() -> None:
    from app.core import admin_auth

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(admin_auth, "get_settings", lambda: SimpleNamespace(admin_api_key="change-me-admin-key"))
    try:
        with pytest.raises(HTTPException) as exc:
            admin_auth.require_admin_key("change-me-admin-key")
        assert exc.value.status_code == 401
        assert exc.value.detail == "ADMIN_KEY_INVALID"
    finally:
        monkeypatch.undo()


def test_alembic_single_head_and_quota_migration_is_isolated() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("script_location", str((os.path.dirname(__file__) or ".") + "/../alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://user:pass@localhost:5432/tendr")

    script = ScriptDirectory.from_config(alembic_cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    # Голова сдвинулась на миграцию Supplier Agent; важно лишь, что она одна
    # (никаких ветвлений) и наследует предыдущую ревизию.
    assert heads == ["e4a91f0b2c77"]
    assert script.get_revision("e4a91f0b2c77").down_revision == "a7c31e9d5b21"
    assert script.get_revision("a7c31e9d5b21").down_revision == "d19b5a2f3b91"

    revision = script.get_revision("d19b5a2f3b91")
    assert revision.down_revision == "lots_partnerships_001"

    source = inspect.getsource(revision.module.upgrade)
    assert '"quota_reservations"' in source
    assert 'op.create_index("ix_quota_reservations_expires_at", "quota_reservations", ["expires_at"], unique=False)' in source
    assert 'op.create_index("ix_quota_reservations_expires", "quota_reservations", ["expires_at"], unique=False)' not in source
    assert "with_variant(sa.Integer, \"sqlite\")" in source


@pytest.mark.asyncio
async def test_goszakup_lookup_uses_full_lot_number_with_graphql_variables() -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "data": {
                    "trd_buy": [{"id": 42, "number_anno": "17549503-1"}],
                    "lots": [{"id": 99, "lot_number": "17549503-1", "trd_buy_id": 42}],
                }
            }

    captured = {}

    class FakeClient:
        async def post(self, url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    parser = GoszakupParser()
    parser._api_token = "token"
    parser._client = FakeClient()

    ref = GoszakupParser.parse_reference("https://v3bl.goszakup.gov.kz/ru/announce/index/17549503-1")
    resolved = await parser.lookup_lot_number(ref)

    assert resolved.lot_number == "17549503-1"
    assert resolved.announcement_id == "42"
    assert resolved.lot_id == "99"
    assert captured["json"]["variables"] == {"lot_number": "17549503-1"}
    assert "$lot_number" in captured["json"]["query"]
    assert "17549503-1" not in captured["json"]["query"].replace("$lot_number", "")


@pytest.mark.asyncio
async def test_goszakup_lookup_handles_timeout_broken_redirect_and_invalid_response() -> None:
    parser = GoszakupParser()
    parser._api_token = "token"

    class TimeoutClient:
        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("slow")

    parser._client = TimeoutClient()
    with pytest.raises(ValueError, match="Timeout"):
        await parser.lookup_lot_number(GoszakupParser.parse_reference("https://goszakup.gov.kz/ru/announce/index/17549503-1"))

    class RedirectClient:
        status_code = 302

        async def post(self, *args, **kwargs):
            return self

    parser._client = RedirectClient()
    with pytest.raises(ValueError, match="redirect"):
        await parser.lookup_lot_number(GoszakupParser.parse_reference("https://goszakup.gov.kz/ru/announce/index/17549503-1"))

    class BrokenJsonClient:
        status_code = 200

        async def post(self, *args, **kwargs):
            return self

        def json(self):
            raise ValueError("bad json")

    parser._client = BrokenJsonClient()
    with pytest.raises(ValueError, match="Повреждённый JSON"):
        await parser.lookup_lot_number(GoszakupParser.parse_reference("https://goszakup.gov.kz/ru/announce/index/17549503-1"))


def test_invalid_reference_does_not_consume_quota() -> None:
    async def _run():
        fake_db = SimpleNamespace()

        async def explode(*args, **kwargs):
            raise AssertionError("quota lookup should not run for invalid URL")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", explode)
        monkeypatch.setattr(lots_api.db_repo, "get_or_create_user", explode)
        try:
            with pytest.raises(HTTPException) as exc:
                await lots_api.analyze_lot_url(
                    req=lots_api.AnalyzeLotRequest(url="https://evil.example/ru/announce/index/17549503-1"),
                    client_id="web_1234567890abcd",
                    db=fake_db,
                )
            assert exc.value.status_code == 400
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_validate_upload_rejects_over_limit() -> None:
    payload = b"x" * 1024
    settings = type(
        "Settings",
        (),
        {"max_upload_bytes": 32, "allowed_frontend_origins": "http://localhost:5173"},
    )()

    with pytest.raises(ValueError):
        lots_api.validate_upload_file(
            filename="bad.pdf",
            content_type="application/pdf",
            data=payload,
            settings=settings,
        )


def test_validate_client_id_rejects_unsafe_values() -> None:
    assert validate_client_id("anon") is False
    assert validate_client_id("") is False
    assert validate_client_id("   ") is False
    assert validate_client_id("abc") is False
    assert validate_client_id("user@domain") is False
    assert validate_client_id("web_1234567890abcd") is True


def test_generate_client_id_returns_safe_random_value() -> None:
    cid = generate_client_id()
    assert validate_client_id(cid) is True
    assert cid.lower() != "anon"
    assert len(cid) >= 16


@pytest.mark.asyncio
async def test_require_client_id_accepts_valid_values() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-client-id", b"web_1234567890abcd")],
        }
    )
    assert await require_client_id(request) == "web_1234567890abcd"


@pytest.mark.asyncio
async def test_require_client_id_rejects_invalid_values() -> None:
    invalid_values = ["", "anon", "short", "web@domain", "a" * 129]
    for value in invalid_values:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"x-client-id", value.encode())],
            }
        )
        with pytest.raises(HTTPException):
            await require_client_id(request)


def test_openapi_routes_do_not_double_prefix_api() -> None:
    paths = app.openapi().get("paths", {})

    expected_paths = [
        "/api/health",
        "/api/lots/search",
        "/api/lots/analyze",
        "/api/lots/analyze-upload",
        "/api/browser/run",
        "/api/account/quota",
        "/api/admin/stats",
        "/api/b2g/workspaces",
        "/api/products/search",
    ]

    for path in expected_paths:
        assert path in paths, f"Required route missing from OpenAPI: {path}"

    offending_paths = sorted(path for path in paths if path.startswith("/api/api/"))
    assert not offending_paths, f"Duplicate API prefix detected: {offending_paths}"


def test_browser_run_requires_client_id() -> None:
    response = client.post(
        "/api/browser/run",
        json={"task": "check_lot_status", "lot_id": "17549503-1"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid client identifier"


def test_browser_session_owner_access_is_enforced() -> None:
    browser_actions._BROWSER_SESSIONS.clear()
    browser_actions._BROWSER_CLIENT_ACTIVE.clear()
    browser_actions._BROWSER_CLIENT_ACTIVITY.clear()

    class FakeAgent:
        async def run_task(self, **kwargs):
            return SimpleNamespace(
                session_id="browser-session-123",
                status="completed",
                output={"ok": True},
                cost_usd=0.1,
                duration_sec=1.2,
                recording_url=None,
                step_count=1,
                live_url=None,
            )

        async def get_status(self, session_id):
            return {"id": session_id, "status": "completed", "live_url": None, "output": {"ok": True}}

        async def continue_session(self, session_id, task):
            return SimpleNamespace(
                session_id=session_id,
                status="completed",
                output={"ok": True},
                cost_usd=0.1,
                duration_sec=1.2,
                step_count=1,
            )

        async def stop_session(self, session_id, strategy="session"):
            return True

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(browser_actions, "BrowserUseAgent", FakeAgent)
    try:
        response = client.post(
            "/api/browser/run",
            json={"task": "check_lot_status", "lot_id": "17549503-1"},
            headers={"X-Client-Id": "web_1234567890abcd"},
        )
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        owner_status = client.get(
            f"/api/browser/status/{session_id}",
            headers={"X-Client-Id": "web_1234567890abcd"},
        )
        assert owner_status.status_code == 200

        other_client = client.get(
            f"/api/browser/status/{session_id}",
            headers={"X-Client-Id": "web_abcdefghijklmno"},
        )
        assert other_client.status_code == 404
        assert other_client.json()["detail"] == "Session not found"
    finally:
        monkeypatch.undo()


def test_browser_run_rejects_invalid_lot_id() -> None:
    response = client.post(
        "/api/browser/run",
        json={"task": "check_lot_status", "lot_id": "not-a-lot"},
        headers={"X-Client-Id": "web_1234567890abcd"},
    )
    assert response.status_code == 422


def test_browser_run_rejects_blocked_host() -> None:
    response = client.post(
        "/api/browser/run",
        json={"task": "check_lot_status", "lot_id": "17549503-1", "url": "https://evil.com"},
        headers={"X-Client-Id": "web_1234567890abcd"},
    )
    assert response.status_code == 422


def test_browser_run_rejects_rate_limit() -> None:
    browser_actions._BROWSER_SESSIONS.clear()
    browser_actions._BROWSER_CLIENT_ACTIVE.clear()
    browser_actions._BROWSER_CLIENT_ACTIVITY.clear()

    class FakeAgent:
        async def run_task(self, **kwargs):
            return SimpleNamespace(
                session_id="browser-session-1",
                status="completed",
                output={"ok": True},
                cost_usd=0.1,
                duration_sec=1.0,
                recording_url=None,
                step_count=1,
                live_url=None,
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(browser_actions, "BrowserUseAgent", FakeAgent)
    try:
        first = client.post(
            "/api/browser/run",
            json={"task": "check_lot_status", "lot_id": "17549503-1"},
            headers={"X-Client-Id": "web_1234567890abcd"},
        )
        assert first.status_code == 200
        second = client.post(
            "/api/browser/run",
            json={"task": "check_lot_status", "lot_id": "17549503-2"},
            headers={"X-Client-Id": "web_1234567890abcd"},
        )
        assert second.status_code == 429
        assert second.json()["detail"] == "RATE_LIMITED"
    finally:
        monkeypatch.undo()


def test_browser_run_returns_safe_error_on_internal_exception() -> None:
    browser_actions._BROWSER_SESSIONS.clear()
    browser_actions._BROWSER_CLIENT_ACTIVE.clear()
    browser_actions._BROWSER_CLIENT_ACTIVITY.clear()

    class FakeAgent:
        async def run_task(self, **kwargs):
            raise RuntimeError("secret token abc")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(browser_actions, "BrowserUseAgent", FakeAgent)
    try:
        response = client.post(
            "/api/browser/run",
            json={"task": "check_lot_status", "lot_id": "17549503-1"},
            headers={"X-Client-Id": "web_1234567890abcd"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "BROWSER_TASK_FAILED"
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_quota_reservation_success_confirm_and_release() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        user = User(web_client_id="web_quota_1")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        reservation = await db_repo.reserve_user_quota(
            session,
            user.id,
            operation_key="analysis:test-1",
            amount=1,
            ttl_seconds=300,
            limit=3,
        )
        assert reservation["status"] == "reserved"
        assert await db_repo.confirm_user_quota(session, user.id, reservation["reservation_key"]) is True
        assert await db_repo.confirm_user_quota(session, user.id, reservation["reservation_key"]) is False
        assert await db_repo.release_user_quota(session, user.id, reservation["reservation_key"]) is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_quota_reservation_exhausts_last_slot_and_expired_reservation_is_released() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        user = User(web_client_id="web_quota_2")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        first = await db_repo.reserve_user_quota(
            session,
            user.id,
            operation_key="analysis:limit-1",
            amount=1,
            ttl_seconds=300,
            limit=1,
        )
        assert first["status"] == "reserved"

        with pytest.raises(db_repo.QuotaLimitExceeded):
            await db_repo.reserve_user_quota(
                session,
                user.id,
                operation_key="analysis:limit-2",
                amount=1,
                ttl_seconds=300,
                limit=1,
            )

        expired = await db_repo.reserve_user_quota(
            session,
            user.id,
            operation_key="analysis:expired-1",
            amount=1,
            ttl_seconds=0,
            limit=2,
        )
        await db_repo.cleanup_expired_quota_reservations(session)
        assert expired["status"] == "reserved"

    await engine.dispose()


@pytest.mark.asyncio
async def test_quota_month_boundary_uses_utc() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        user = User(web_client_id="web_quota_3")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        quota = await db_repo.get_user_quota(session, user.id, limit=3, now_override=None)
        assert quota["limit"] == 3
        assert quota["used_this_month"] == 0

    await engine.dispose()


def test_validate_upload_file_accepts_small_valid_txt() -> None:
    settings = type("Settings", (), {"max_upload_bytes": 10 * 1024 * 1024})()
    lots_api.validate_upload_file(
        filename="brief.txt",
        content_type="text/plain",
        data=b"hello world",
        settings=settings,
    )


def test_validate_upload_file_rejects_empty_file() -> None:
    settings = type("Settings", (), {"max_upload_bytes": 10 * 1024 * 1024})()
    with pytest.raises(lots_api.UploadValidationError, match="EMPTY_FILE"):
        lots_api.validate_upload_file(
            filename="empty.txt",
            content_type="text/plain",
            data=b"",
            settings=settings,
        )


def test_validate_upload_file_rejects_oversize_chunked() -> None:
    async def _read_chunks():
        file = UploadFile(filename="big.txt", file=io.BytesIO(b"x" * 128))
        payload = await lots_api.read_upload_file_safely(file, max_bytes=64)
        assert payload == b""

    with pytest.raises(lots_api.UploadValidationError, match="FILE_TOO_LARGE"):
        async def _run():
            file = UploadFile(filename="big.txt", file=io.BytesIO(b"x" * 128))
            await lots_api.read_upload_file_safely(file, max_bytes=64)

        import asyncio
        asyncio.run(_run())


def test_validate_upload_file_rejects_invalid_extension_mime_or_signature() -> None:
    settings = type("Settings", (), {"max_upload_bytes": 10 * 1024 * 1024})()
    with pytest.raises(lots_api.UploadValidationError):
        lots_api.validate_upload_file(
            filename="report.pdf.exe",
            content_type="application/pdf",
            data=b"%PDF-1.4",
            settings=settings,
        )
    with pytest.raises(lots_api.UploadValidationError):
        lots_api.validate_upload_file(
            filename="report.pdf",
            content_type="text/plain",
            data=b"%PDF-1.4",
            settings=settings,
        )
    with pytest.raises(lots_api.UploadValidationError):
        lots_api.validate_upload_file(
            filename="report.pdf",
            content_type="application/pdf",
            data=b"NOTPDF",
            settings=settings,
        )


def test_validate_upload_file_rejects_zip_bomb_and_path_traversal() -> None:
    payload = b"PK\x03\x04"
    with pytest.raises(lots_api.UploadValidationError):
        lots_api._validate_zip_container(payload)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../evil.txt", "boom")
    with pytest.raises(lots_api.UploadValidationError):
        lots_api._validate_zip_container(zip_buffer.getvalue())

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("good.txt", "x" * 200000)
    with pytest.raises(lots_api.UploadValidationError):
        lots_api._validate_zip_container(zip_buffer.getvalue())


def test_analyze_lot_upload_skips_invalid_file_before_ai_and_quota() -> None:
    async def _run():
        fake_db = SimpleNamespace()
        called = {"ai": False, "quota": False}

        async def fake_get_user_by_web_id(db, cid):
            called["quota"] = True
            return None

        async def fake_create_user(db, web_client_id):
            return SimpleNamespace(id=7)

        async def fake_get_quota(db, user_id):
            return {"monthly_limit": 3, "used_this_month": 0, "is_pilot": False}

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", fake_get_user_by_web_id)
        monkeypatch.setattr(lots_api.db_repo, "get_or_create_user", fake_create_user)
        monkeypatch.setattr(lots_api.db_repo, "get_user_quota", fake_get_quota)

        async def fake_ai(*args, **kwargs):
            called["ai"] = True
            return SimpleNamespace(model_dump=lambda: {"ok": True})

        monkeypatch.setattr(lots_api, "analyze_uploaded_file", fake_ai)
        try:
            file = UploadFile(
                filename="bad.pdf",
                file=io.BytesIO(b"NOPE"),
                headers={"content-type": "application/pdf"},
            )
            with pytest.raises(HTTPException) as exc:
                await lots_api.analyze_lot_upload(
                    client_id="web_1234567890abcd",
                    db=fake_db,
                    file=file,
                )
            assert exc.value.status_code == 422
            assert called["ai"] is False
            assert called["quota"] is False
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_analyze_lot_upload_safe_error_when_parser_raises() -> None:
    async def _run():
        fake_db = SimpleNamespace()

        async def fake_get_user_by_web_id(db, cid):
            return SimpleNamespace(id=7)

        async def fake_get_quota(db, user_id):
            return {"monthly_limit": 3, "used_this_month": 0, "is_pilot": False}

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", fake_get_user_by_web_id)
        monkeypatch.setattr(lots_api.db_repo, "get_user_quota", fake_get_quota)

        async def fake_ai(*args, **kwargs):
            raise RuntimeError("secret internal token 123")

        monkeypatch.setattr(lots_api, "analyze_uploaded_file", fake_ai)
        try:
            file = UploadFile(
                filename="brief.txt",
                file=io.BytesIO(b"hello world"),
                headers={"content-type": "text/plain"},
            )
            with pytest.raises(HTTPException) as exc:
                await lots_api.analyze_lot_upload(
                    client_id="web_1234567890abcd",
                    db=fake_db,
                    file=file,
                )
            assert exc.value.status_code == 500
            assert exc.value.detail == "FILE_PROCESSING_FAILED"
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_temp_file_removed_on_exception() -> None:
    async def _run():
        fake_db = SimpleNamespace()
        deleted = []

        async def fake_get_user_by_web_id(db, cid):
            return SimpleNamespace(id=7)

        async def fake_get_quota(db, user_id):
            return {"monthly_limit": 3, "used_this_month": 0, "is_pilot": False}

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", fake_get_user_by_web_id)
        monkeypatch.setattr(lots_api.db_repo, "get_user_quota", fake_get_quota)

        async def fake_ai(*args, **kwargs):
            temp_path = args[0]
            assert os.path.exists(temp_path)
            raise RuntimeError("boom")

        monkeypatch.setattr(lots_api, "analyze_uploaded_file", fake_ai)

        real_unlink = os.unlink

        def tracking_unlink(path):
            deleted.append(path)
            return real_unlink(path)

        monkeypatch.setattr(os, "unlink", tracking_unlink)
        try:
            file = UploadFile(
                filename="brief.txt",
                file=io.BytesIO(b"hello world"),
                headers={"content-type": "text/plain"},
            )
            with pytest.raises(HTTPException):
                await lots_api.analyze_lot_upload(
                    client_id="web_1234567890abcd",
                    db=fake_db,
                    file=file,
                )
            assert deleted
            for path in deleted:
                assert not os.path.exists(path)
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_safe_error_for_external_service_response() -> None:
    async def _run():
        class FakeResp:
            status_code = 502
            content = b'{}'

            def json(self):
                return {"error": "secret-token=abc"}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return FakeResp()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(admin_api, "get_settings", lambda: SimpleNamespace(
            goszakup_api_token="super-secret-token",
            goszakup_api_url="https://ows.goszakup.gov.kz/v2",
        ))
        monkeypatch.setattr(admin_api.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())
        try:
            result = await admin_api.token_check(_admin=None)
            assert result["status"] in {"unavailable", "invalid"}
            assert "secret" not in str(result).lower()
            assert "super-secret-token" not in str(result)
            assert "ows.goszakup.gov.kz" not in str(result)
            assert "token" not in str(result).lower()
            assert "error_code" in result
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_admin_auth_dependency_is_single_and_safe() -> None:
    from app.core import admin_auth

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(admin_auth, "get_settings", lambda: SimpleNamespace(admin_api_key=""))
    try:
        with pytest.raises(HTTPException) as exc:
            admin_auth.require_admin_key(None)
        assert exc.value.status_code == 401
        assert exc.value.detail == "ADMIN_KEY_INVALID"

        monkeypatch.setattr(admin_auth, "get_settings", lambda: SimpleNamespace(admin_api_key="safe-key"))
        assert admin_auth.require_admin_key("safe-key") is None
        with pytest.raises(HTTPException):
            admin_auth.require_admin_key("wrong")
    finally:
        monkeypatch.undo()


def test_admin_token_check_security_contract() -> None:
    async def _run():
        monkeypatch = pytest.MonkeyPatch()

        def fake_settings():
            return SimpleNamespace(
                goszakup_api_token="token-abc",
                goszakup_api_url="https://ows.goszakup.gov.kz/v2",
            )

        monkeypatch.setattr(admin_api, "get_settings", fake_settings)

        class OkResp:
            status_code = 200
            content = b'{"data":{"trd_buy":[{"id":1}]}}'

            def json(self):
                return {"data": {"trd_buy": [{"id": 1}]}}

        class OkClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return OkResp()

        class FailClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                raise httpx.TimeoutException("slow")

        class RedirectClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                class RedirectResp:
                    status_code = 302
                    content = b"redirect"
                return RedirectResp()

        class BadJsonClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                class BadResp:
                    status_code = 200
                    content = b'{broken json'

                    def json(self):
                        raise ValueError("bad json")
                return BadResp()

        try:
            monkeypatch.setattr(admin_api.httpx, "AsyncClient", OkClient)
            result = await admin_api.token_check(_admin=None)
            assert result["status"] == "valid"
            assert "token" not in str(result).lower()

            monkeypatch.setattr(admin_api.httpx, "AsyncClient", FailClient)
            result = await admin_api.token_check(_admin=None)
            assert result["status"] == "unavailable"
            assert result["error_code"] == "GOSZAKUP_TIMEOUT"

            monkeypatch.setattr(admin_api.httpx, "AsyncClient", RedirectClient)
            result = await admin_api.token_check(_admin=None)
            assert result["status"] == "invalid"
            assert result["error_code"] == "GOSZAKUP_REDIRECT"

            monkeypatch.setattr(admin_api.httpx, "AsyncClient", BadJsonClient)
            result = await admin_api.token_check(_admin=None)
            assert result["status"] == "invalid"
            assert result["error_code"] == "GOSZAKUP_BAD_RESPONSE"
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_admin_routes_require_x_admin_key() -> None:
    response = client.get("/api/admin/stats")
    assert response.status_code == 401
    assert response.json()["detail"] == "ADMIN_KEY_INVALID"

    response = client.get("/api/admin/stats", headers={"X-Admin-Key": "wrong-key"})
    assert response.status_code == 401
    assert response.json()["detail"] == "ADMIN_KEY_INVALID"

    from app.core import admin_auth
    from app.api import account as account_api

    assert account_api.require_admin_key is admin_auth.require_admin_key
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(admin_auth, "get_settings", lambda: SimpleNamespace(admin_api_key="admin-test-key"))
    try:
        assert admin_auth.require_admin_key("admin-test-key") is None
        with pytest.raises(HTTPException):
            admin_auth.require_admin_key("wrong-key")
    finally:
        monkeypatch.undo()


def test_lots_analysis_failure_exposes_only_safe_message() -> None:
    async def _run():
        fake_db = SimpleNamespace()

        async def fake_get_user_by_web_id(db, cid):
            return SimpleNamespace(id=7)

        async def fake_get_user_quota(db, user_id):
            return {"monthly_limit": 3, "used_this_month": 0, "is_pilot": False}

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", fake_get_user_by_web_id)
        monkeypatch.setattr(lots_api.db_repo, "get_or_create_user", lambda db, web_client_id: SimpleNamespace(id=7))
        monkeypatch.setattr(lots_api.db_repo, "get_user_quota", fake_get_user_quota)

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("secret internal token 123")

        monkeypatch.setattr(lots_api, "GoszakupParser", SimpleNamespace(_normalize_reference=lambda url: "12345"))
        monkeypatch.setattr(lots_api, "LotOrchestrator", FakeOrchestrator)
        try:
            with pytest.raises(HTTPException) as exc:
                await lots_api.analyze_lot_url(
                    req=lots_api.AnalyzeLotRequest(url="https://goszakup.gov.kz/ru/announce/index/12345"),
                    client_id="web_1234567890abcd",
                    db=fake_db,
                )
            assert exc.value.status_code == 500
            assert exc.value.detail == "ANALYSIS_FAILED"
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_history_route_returns_only_current_user_records() -> None:
    async def _run():
        fake_db = SimpleNamespace()

        class FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return SimpleNamespace(all=lambda: self._rows)

        async def fake_get_user_by_web_id(db, cid):
            return SimpleNamespace(id=7) if cid == "web_1234567890abcd" else None

        async def fake_get_user_history(db, user_id, limit=20, offset=0):
            assert user_id == 7
            return [
                SimpleNamespace(
                    lot_id="1001",
                    title="Alpha",
                    customer="Customer A",
                    method="tender",
                    overall_risk="high",
                    n_requirements=2,
                    n_red_flags=1,
                    created_at=__import__("datetime").datetime(2024, 1, 2, 3, 4, 5),
                    result_json={"lot": {"title": "Alpha", "customer": "Customer A", "method": "tender", "requirements": [1], "red_flags": ["x"]}, "legal": {"overall_risk": "high"}},
                )
            ]

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", fake_get_user_by_web_id)
        monkeypatch.setattr(lots_api.db_repo, "get_user_history", fake_get_user_history)
        try:
            result = await lots_api.get_lot_history(
                client_id="web_1234567890abcd",
                db=fake_db,
                limit=20,
                offset=0,
            )
            assert result["items"][0]["lot_id"] == "1001"
            assert result["items"][0]["title"] == "Alpha"
            assert result["items"][0]["customer"] == "Customer A"
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())


def test_download_route_rejects_unknown_kind_and_missing_document() -> None:
    async def _run():
        fake_db = SimpleNamespace()
        analysis = SimpleNamespace(
            user_id=7,
            lot_id="42",
            result_json={
                "lot": {"lot_id": "42", "title": "Title", "customer": "Customer", "method": "tender"},
                "legal": {"overall_risk": "medium"},
            },
        )

        class FakeSelectResult:
            def __init__(self, row):
                self._row = row

            def scalar_one_or_none(self):
                return self._row

        async def fake_execute(stmt):
            return FakeSelectResult(analysis)

        async def fake_get_user_by_web_id(db, cid):
            return SimpleNamespace(id=7)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lots_api.db_repo, "get_user_by_web_id", fake_get_user_by_web_id)
        monkeypatch.setattr(fake_db, "execute", fake_execute, raising=False)
        try:
            with pytest.raises(HTTPException) as exc:
                await lots_api.download_lot_document(
                    lot_id=42,
                    kind="unknown",
                    client_id="web_1234567890abcd",
                    db=fake_db,
                )
            assert exc.value.status_code == 400

            with pytest.raises(HTTPException) as exc2:
                await lots_api.download_lot_document(
                    lot_id=42,
                    kind="complaint",
                    client_id="web_1234567890abcd",
                    db=fake_db,
                )
            assert exc2.value.status_code == 404
        finally:
            monkeypatch.undo()

    import asyncio
    asyncio.run(_run())
