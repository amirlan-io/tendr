from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.core.config import get_settings

_PLACEHOLDER_ADMIN_KEYS = {
    "change-me-admin-key",
    "changeme",
    "admin",
    "admin-api-key",
    "replace-me",
    "your-admin-key-here",
}


def _is_placeholder_admin_key(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDER_ADMIN_KEYS


def require_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Protect admin endpoints with a single server-side dependency."""
    configured = (get_settings().admin_api_key or "").strip()

    # Значение из .env может оказаться не ключом, а комментарием или
    # мусором (например «ADMIN_API_KEY=   # сгенерируйте ключ» —
    # такой случай встречался в реальном .env). Такую конфигурацию нужно
    # считать «не настроено», а не ронять 500 внутри hmac.
    if configured.startswith("#"):
        configured = ""
    if _is_placeholder_admin_key(configured):
        raise HTTPException(status_code=401, detail="ADMIN_KEY_INVALID")
    if not configured or not x_admin_key:
        raise HTTPException(status_code=401, detail="ADMIN_KEY_INVALID")
    # compare_digest для строк принимает только ASCII; ключи в UTF-8
    # сравниваем по байтам, иначе возможен TypeError вместо 401.
    if not hmac.compare_digest(
        x_admin_key.encode("utf-8"), configured.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="ADMIN_KEY_INVALID")

