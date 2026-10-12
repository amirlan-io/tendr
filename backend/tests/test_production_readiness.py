from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "prod",
        "database_url": "postgresql+asyncpg://tendr:password@postgres:5432/tendr",
        "database_url_sync": "postgresql://tendr:password@postgres:5432/tendr",
        "redis_url": "redis://redis:6379/0",
        "analysis_job_mode": "redis",
        "analysis_job_storage_dir": "/var/lib/tendr/analysis-jobs",
        "allowed_hosts": "api.tendr.example",
        "allowed_frontend_origins": "https://tendr.example",
        "supabase_url": "https://project.supabase.co",
        "supabase_publishable_key": "publishable-test-value",
        "llm_api_key": "llm-test-value",
        "goszakup_api_token": "goszakup-test-value",
        "tavily_api_key": "tavily-test-value",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_accepts_shared_services_and_core_providers() -> None:
    settings = _production_settings()

    assert settings.app_env == "prod"
    assert settings.analysis_job_mode == "redis"
    assert settings.allowed_hosts_list == ["api.tendr.example"]


@pytest.mark.parametrize(
    "field",
    [
        "analysis_job_storage_dir",
        "supabase_url",
        "supabase_publishable_key",
        "llm_api_key",
        "goszakup_api_token",
        "tavily_api_key",
    ],
)
def test_production_rejects_missing_core_service(field: str) -> None:
    with pytest.raises(ValidationError):
        _production_settings(**{field: ""})


def test_production_rejects_local_job_runner() -> None:
    with pytest.raises(ValidationError):
        _production_settings(analysis_job_mode="local")
