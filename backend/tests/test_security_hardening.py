from __future__ import annotations

import io

import pytest

from app.api import lots as lots_api
from app.core.client_id import generate_client_id, validate_client_id
from app.services.goszakup_parser import GoszakupParser


def test_extract_reference_rejects_untrusted_host() -> None:
    with pytest.raises(ValueError):
        GoszakupParser._normalize_reference("https://evil.example/ru/announce/index/17266377")


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
