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
    if _is_placeholder_admin_key(configured):
        raise HTTPException(status_code=401, detail="ADMIN_KEY_INVALID")
    if not configured or not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        raise HTTPException(status_code=401, detail="ADMIN_KEY_INVALID")

    return None
