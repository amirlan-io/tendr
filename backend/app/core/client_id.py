from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import HTTPException, Request

from app.core.supabase_auth import get_optional_supabase_user, supabase_client_id

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MIN_CLIENT_ID_LEN = 16
MAX_CLIENT_ID_LEN = 128

#: Префикс гостевой идентичности. Авторизованные пользователи получают
#: `supabase_<uuid>` (см. supabase_auth.supabase_client_id), поэтому гостю
#: запрещено значение с таким префиксом — иначе знание чужого UUID из
#: утечки (например, из списка участников) позволяло выдать себя за него
#: без токена (аудит 2026-10-03, P0 #1).
GUEST_PREFIX = "gst_"
RESERVED_GUEST_PREFIXES = ("supabase_", "anon")


def validate_client_id(value: Any) -> bool:
    """Проверить формат web_client_id.

    Это проверка ЗНАЧЕНИЯ В БД, а не гостевого ввода: сюда попадают и
    `gst_*`, и `supabase_*`. Запрет зарезервированных префиксов живёт в
    validate_guest_client_id.
    """
    if value is None:
        return False
    if not isinstance(value, str):
        return False

    candidate = value.strip()
    if not candidate:
        return False
    if candidate == "anon":
        return False
    if len(candidate) < MIN_CLIENT_ID_LEN or len(candidate) > MAX_CLIENT_ID_LEN:
        return False
    return bool(CLIENT_ID_RE.fullmatch(candidate))


def validate_guest_client_id(value: Any) -> bool:
    """Проверить идентификатор, присланный браузером БЕЗ токена.

    Значения авторизованных пользователей здесь недопустимы намеренно: этот
    путь не имеет токена, поэтому принять `supabase_<uuid>` значит выдать
    себя за этого пользователя.
    """
    if not validate_client_id(value):
        return False
    candidate = str(value).strip()
    return not candidate.lower().startswith(RESERVED_GUEST_PREFIXES)


async def require_client_id(request: Request) -> str:
    """Resolve an authenticated identity or a validated guest client ID.

    A valid Supabase bearer token always wins over the browser-controlled client
    ID. Requests without a bearer token keep the existing guest behavior, but
    get a namespaced ID: гостевой и авторизованный идентификаторы больше не
    пересекаются, поэтому подмена `X-Client-Id: supabase_<uuid>` больше не
    открывает чужие данные.
    """
    auth_user = await get_optional_supabase_user(request)
    if auth_user is not None:
        return supabase_client_id(auth_user)

    raw = request.cookies.get("tendr_cid") or request.headers.get("X-Client-Id")
    if not validate_guest_client_id(raw):
        raise HTTPException(status_code=400, detail="Invalid client identifier")
    # Гость хранится под собственным пространством имён.
    return f"{GUEST_PREFIX}{raw}"


def generate_client_id() -> str:
    """Create a safe random client identifier for browser sessions."""
    while True:
        candidate = secrets.token_urlsafe(24)
        if validate_guest_client_id(candidate):
            return candidate
