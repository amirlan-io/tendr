"""Центральный конфиг приложения. Загружается из .env через pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_csv(value: str) -> list[str]:
    if value is None:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for raw in str(value).split(","):
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Общее ===
    app_env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "tendr"
    default_lang: Literal["ru", "kk"] = "ru"
    log_level: str = "INFO"
    enable_openapi_in_prod: bool = False

    # === БД ===
    database_url: str = "postgresql+asyncpg://tendr:tendr@localhost:5432/tendr"
    database_url_sync: str = "postgresql://tendr:tendr@localhost:5432/tendr"

    # === Redis ===
    redis_url: str = "redis://localhost:6379/0"

    # === LLM ===
    llm_provider: Literal["mistral", "alem", "openai-compatible"] = "mistral"
    llm_api_key: str = ""
    llm_api_key_fallback: str = ""  # ключ резервного провайдера
    llm_base_url: str = "https://api.mistral.ai/v1"
    llm_model: str = "mistral-large-latest"
    llm_embedding_model: str = "mistral-embed"
    embedding_dim: int = 1024

    # === Tavily (поиск товаров) ===
    tavily_api_key: str = ""
    tavily_max_results: int = 10
    # Провайдер эмбеддингов: "local" (sentence-transformers) или "llm"
    embedding_provider: Literal["local", "llm"] = "llm"
    embedding_local_model: str = "intfloat/multilingual-e5-small"

    # === AlemLLM (резервный OpenAI-совместимый) ===
    alem_base_url: str = "https://llm.alem.ai/v1"
    alem_model: str = "qwen3-6"

    # === Telegram ===
    bot_token: str = ""
    admin_telegram_ids: str = ""  # CSV

    # === goszakup.gov.kz ===
    goszakup_api_url: str = "https://ows.goszakup.gov.kz/v2"
    goszakup_api_token: str = ""
    goszakup_public_base_url: str = "https://goszakup.gov.kz"

    # === Admin ===
    admin_api_key: str = ""
    admin_api_key_header: str = "X-Admin-Key"

    # === Supabase Auth ===
    # Publishable/anon key is intentionally used here. Never configure a
    # service_role or secret key in the browser application.
    supabase_url: str = ""
    supabase_publishable_key: str = ""

    # === Security ===
    max_upload_bytes: int = 20 * 1024 * 1024
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    allowed_frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # === Qdrant ===
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # === Browser Use (облачный браузерный агент) ===
    browser_use_api_key: str = ""

    # === Freemium ===
    free_tier_applications_per_month: int = 3
    pilot_free_tier_applications_per_month: int = 999

    # === Наблюдаемость ===
    sentry_dsn: str = ""

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: str) -> str:
        hosts = _normalize_csv(value)
        if not hosts:
            raise ValueError("allowed_hosts must contain at least one trusted host")
        for host in hosts:
            if host == "*":
                raise ValueError("Wildcard host is not allowed")
            if host.startswith("http://") or host.startswith("https://"):
                raise ValueError("Allowed hosts must be bare hostnames, not URLs")
            if "/" in host or "?" in host or "#" in host or "@" in host:
                raise ValueError("Allowed hosts cannot contain path/query/userinfo")
        return ",".join(hosts)

    @field_validator("allowed_frontend_origins")
    @classmethod
    def validate_allowed_frontend_origins(cls, value: str) -> str:
        origins = _normalize_csv(value)
        if not origins:
            raise ValueError("allowed_frontend_origins must contain at least one origin")
        for origin in origins:
            if origin == "*":
                raise ValueError("Wildcard CORS origin is not allowed")
            parts = urlsplit(origin)
            if parts.scheme not in {"http", "https"}:
                raise ValueError("Allowed frontend origins must use http or https")
            if not parts.hostname or parts.username or parts.password:
                raise ValueError("Allowed frontend origins must be exact origins without credentials")
            if parts.path not in {"", "/"} or parts.query or parts.fragment:
                raise ValueError("Allowed frontend origins must not include path, query or fragment")
        return ",".join(origins)

    @model_validator(mode="after")
    def validate_runtime_security(self) -> "Settings":
        if self.app_env == "prod":
            hosts = self.allowed_hosts_list
            origins = self.allowed_frontend_origins_list
            if not hosts:
                raise ValueError("Production requires a non-empty allowed_hosts list")
            if not origins:
                raise ValueError("Production requires a non-empty allowed_frontend_origins list")
            if any(host in {"localhost", "127.0.0.1", "0.0.0.0", "testserver", "*"} for host in hosts):
                raise ValueError("Localhost/testserver hosts are not allowed in production")
            if any(origin.lower().startswith(("http://localhost", "http://127.0.0.1", "https://localhost", "https://127.0.0.1")) for origin in origins):
                raise ValueError("Localhost origins are not allowed in production")
            if any(origin == "*" for origin in origins):
                raise ValueError("Wildcard CORS is not allowed in production")
            placeholder_keys = {"change-me-admin-key", "changeme", "admin", "admin-api-key", "replace-me", "your-admin-key-here"}
            configured_key = (self.admin_api_key or "").strip().lower()
            if configured_key and configured_key in placeholder_keys:
                raise ValueError("Production admin_api_key cannot use a placeholder value")
        return self

    @property
    def allowed_hosts_list(self) -> list[str]:
        return _normalize_csv(self.allowed_hosts)

    @property
    def allowed_frontend_origins_list(self) -> list[str]:
        return _normalize_csv(self.allowed_frontend_origins)

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x) for x in self.admin_telegram_ids.split(",") if x.strip().isdigit()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
