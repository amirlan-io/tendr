from __future__ import annotations

import re
import secrets
from typing import Any

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MIN_CLIENT_ID_LEN = 16
MAX_CLIENT_ID_LEN = 128


def validate_client_id(value: Any) -> bool:
    """Return True only for strict, non-anonymous client IDs."""
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


def generate_client_id() -> str:
    """Create a safe random client identifier for browser sessions."""
    while True:
        candidate = secrets.token_urlsafe(24)
        if validate_client_id(candidate):
            return candidate
