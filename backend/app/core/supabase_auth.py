"""Server-side validation for Supabase email authentication.

The browser session is never trusted on its own. Every bearer token used by
the API is validated against Supabase Auth's ``/auth/v1/user`` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException, Request, status

from app.core.config import get_settings

MAX_AUTH_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class SupabaseUser:
    id: str
    email: str | None


def _auth_error(detail: str = "AUTH_REQUIRED") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("Authorization", "").strip()
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise _auth_error("INVALID_AUTH_TOKEN")
    token = token.strip()
    if len(token) > 8192:
        raise _auth_error("INVALID_AUTH_TOKEN")
    return token


def _validated_auth_url(raw_url: str) -> str:
    base_url = raw_url.strip().rstrip("/")
    parts = urlsplit(base_url)
    is_local = parts.hostname in {"localhost", "127.0.0.1"}
    if (
        parts.scheme not in ({"http", "https"} if is_local else {"https"})
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise HTTPException(status_code=503, detail="AUTH_NOT_CONFIGURED")
    return f"{base_url}/auth/v1/user"


async def get_optional_supabase_user(request: Request) -> SupabaseUser | None:
    """Return the authenticated user, or ``None`` for a guest request."""
    token = _bearer_token(request)
    if token is None:
        return None

    settings = get_settings()
    publishable_key = settings.supabase_publishable_key.strip()
    if not settings.supabase_url.strip() or not publishable_key:
        raise HTTPException(status_code=503, detail="AUTH_NOT_CONFIGURED")

    auth_url = _validated_auth_url(settings.supabase_url)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                auth_url,
                headers={
                    "apikey": publishable_key,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="AUTH_UNAVAILABLE") from exc

    if response.status_code != 200:
        raise _auth_error("INVALID_AUTH_TOKEN")
    if len(response.content) > MAX_AUTH_RESPONSE_BYTES:
        raise HTTPException(status_code=503, detail="AUTH_UNAVAILABLE")

    try:
        payload = response.json()
        subject = str(UUID(str(payload["id"])))
        raw_email = payload.get("email")
        email = str(raw_email).strip().lower() if raw_email else None
    except (KeyError, TypeError, ValueError) as exc:
        raise _auth_error("INVALID_AUTH_TOKEN") from exc

    if email and len(email) > 255:
        raise _auth_error("INVALID_AUTH_TOKEN")
    return SupabaseUser(id=subject, email=email)


async def require_supabase_user(request: Request) -> SupabaseUser:
    user = await get_optional_supabase_user(request)
    if user is None:
        raise _auth_error()
    return user


def supabase_client_id(user: SupabaseUser) -> str:
    """Map a verified Supabase subject to the existing stable web identity."""
    return f"supabase_{user.id.replace('-', '')}"
