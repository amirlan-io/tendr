from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import client_id as client_id_module
from app.core import supabase_auth
from app.core.supabase_auth import SupabaseUser


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("ascii")))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class _FakeResponse:
    status_code = 200
    content = b'{"id":"7e3527d8-d852-4d8d-97e7-da7f5db0ecac","email":"USER@EXAMPLE.COM"}'

    def json(self):
        return {
            "id": "7e3527d8-d852-4d8d-97e7-da7f5db0ecac",
            "email": "USER@EXAMPLE.COM",
        }


class _FakeClient:
    def __init__(self, **_kwargs):
        self.request_headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url, *, headers):
        self.request_headers = headers
        return _FakeResponse()


@pytest.mark.asyncio
async def test_supabase_bearer_is_validated_server_side(monkeypatch):
    monkeypatch.setattr(
        supabase_auth,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://project.supabase.co",
            supabase_publishable_key="public-key",
        ),
    )
    monkeypatch.setattr(supabase_auth.httpx, "AsyncClient", _FakeClient)

    user = await supabase_auth.get_optional_supabase_user(
        _request("Bearer signed-access-token")
    )

    assert user == SupabaseUser(
        id="7e3527d8-d852-4d8d-97e7-da7f5db0ecac",
        email="user@example.com",
    )
    assert supabase_auth.supabase_client_id(user).startswith("supabase_")


@pytest.mark.asyncio
async def test_missing_bearer_stays_guest():
    assert await supabase_auth.get_optional_supabase_user(_request()) is None


@pytest.mark.asyncio
async def test_invalid_authorization_scheme_is_rejected():
    with pytest.raises(HTTPException) as error:
        await supabase_auth.get_optional_supabase_user(_request("Basic abc"))
    assert error.value.status_code == 401
    assert error.value.detail == "INVALID_AUTH_TOKEN"


@pytest.mark.asyncio
async def test_verified_user_overrides_browser_client_id(monkeypatch):
    async def authenticated(_request):
        return SupabaseUser(
            id="7e3527d8-d852-4d8d-97e7-da7f5db0ecac",
            email="user@example.com",
        )

    monkeypatch.setattr(client_id_module, "get_optional_supabase_user", authenticated)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-client-id", b"aaaaaaaaaaaaaaaa")],
        }
    )
    resolved = await client_id_module.require_client_id(request)
    assert resolved == "supabase_7e3527d8d8524d8d97e7da7f5db0ecac"
