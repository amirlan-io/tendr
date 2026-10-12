"""Центральный конфиг приложения. Загружается из .env через pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path:
    """Find the project .env, with backward-compatible backend/.env support.

    Раньше здесь был жёсткий ``parents[2]``, но он указывал на каталог
    ``backend/``, а не на корень проекта: файл не читался, и приложение
    стартовало с настройками по умолчанию (LLM_API_KEY пуст). Из-за этого
    приходилось вручную передавать переменные окружения при запуске.
    The repository root is preferred. Existing local installations that still
    keep secrets in ``backend/.env`` continue to work until they are migrated.
    """
    here = Path(__file__).resolve()
    project_root = here.parents[3]
    project_env = project_root / ".env"
    legacy_backend_env = here.parents[2] / ".env"
    if project_env.is_file():
        return project_env
    if legacy_backend_env.is_file():
        return legacy_backend_env
    return project_env


_BACKEND_ENV_FILE = _find_env_file()


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
        # Не зависит от cwd: ключ Goszakup загружается и при запуске из корня,
        # и при запуске непосредственно из backend/.
        env_file=str(_BACKEND_ENV_FILE),
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
    analysis_job_mode: Literal["local", "redis"] = "local"
    analysis_job_queue_name: str = "tendr:analysis:jobs"

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
    # Upper bound per supplier search; basic queries cost fewer credits than
    # the old unconditional advanced searches.
    supplier_search_max_calls: int = 4
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
    goszakup_api_url: str = "https://ows.goszakup.gov.kz/v3"
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
    analysis_job_storage_dir: str = ""
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    allowed_frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # === Qdrant ===
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # === Browser Use (облачный браузерный агент) ===
    browser_use_api_key: str = ""
    # V4 (рекомендованный API). Значения по умолчанию — из документации.
    browser_use_base_url: str = "https://api.browser-use.com/api/v4"
    browser_use_model: str = "gpt-5.6-luna"
    # Потолок стоимости одного запуска агента в USD. Клиент дополнительно
    # ограничивает значение жёстким пределом, поэтому опечатка в .env
    # не превратится в неограниченный счёт.
    browser_use_max_cost_usd: float = 1.0

    # Optional SSH browser worker. Credentials stay on the application host,
    # never in the repository or in a browser request.
    browser_worker_ssh_target: str = ""
    browser_worker_ssh_key_file: str = ""
    browser_worker_ssh_known_hosts: str = ""

    # === Freemium ===
    free_tier_applications_per_month: int = 3
    pilot_free_tier_applications_per_month: int = 999

    # === Billing (Stripe Checkout) ===
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_plus: str = ""
    stripe_price_pro: str = ""
    stripe_price_ultra: str = ""
    billing_success_url: str = "http://localhost:5173/dashboard/billing?payment=success"
    billing_cancel_url: str = "http://localhost:5173/dashboard/billing?payment=cancelled"

    # === Supplier outreach ===
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_starttls: bool = True
    smtp_use_ssl: bool = False
    leximo_api_token: str = ""
    leximo_agent_id: str = ""

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

    @field_validator("goszakup_api_url")
    @classmethod
    def validate_goszakup_api_url(cls, value: str) -> str:
        """Не позволяет передать секретный API-токен на посторонний хост."""
        normalized = value.strip().rstrip("/")
        parts = urlsplit(normalized)
        if (
            parts.scheme != "https"
            or parts.hostname != "ows.goszakup.gov.kz"
            or parts.username
            or parts.password
            or parts.port not in {None, 443}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Goszakup API URL must use the official HTTPS host")
        if not parts.path.startswith(("/v2", "/v3")):
            raise ValueError("Goszakup API URL must point to a supported API version")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_security(self) -> Settings:
        if self.app_env == "prod":
            hosts = self.allowed_hosts_list
            origins = self.allowed_frontend_origins_list
            if not hosts:
                raise ValueError("Production requires a non-empty allowed_hosts list")
            if not origins:
                raise ValueError("Production requires a non-empty allowed_frontend_origins list")
            if any(host in {"localhost", "127.0.0.1", "0.0.0.0", "testserver", "*"} for host in hosts):
                raise ValueError("Localhost/testserver hosts are not allowed in production")
            local_origins = (
                "http://localhost",
                "http://127.0.0.1",
                "https://localhost",
                "https://127.0.0.1",
            )
            if any(origin.lower().startswith(local_origins) for origin in origins):
                raise ValueError("Localhost origins are not allowed in production")
            if any(origin == "*" for origin in origins):
                raise ValueError("Wildcard CORS is not allowed in production")
            placeholder_keys = {"change-me-admin-key", "changeme", "admin", "admin-api-key", "replace-me", "your-admin-key-here"}
            configured_key = (self.admin_api_key or "").strip().lower()
            if configured_key and configured_key in placeholder_keys:
                raise ValueError("Production admin_api_key cannot use a placeholder value")
            if not self.database_url.startswith("postgresql+"):
                raise ValueError("Production requires PostgreSQL DATABASE_URL")
            if not self.database_url_sync.startswith("postgresql://"):
                raise ValueError("Production requires PostgreSQL DATABASE_URL_SYNC")
            if self.analysis_job_mode != "redis" or not self.redis_url.strip():
                raise ValueError("Production requires Redis-backed analysis jobs")
            if not self.analysis_job_storage_dir.strip():
                raise ValueError("Production requires a persistent shared ANALYSIS_JOB_STORAGE_DIR")
            required = {
                "SUPABASE_URL": self.supabase_url,
                "SUPABASE_PUBLISHABLE_KEY": self.supabase_publishable_key,
                "LLM_API_KEY": self.llm_api_key,
                "GOSZAKUP_API_TOKEN": self.goszakup_api_token,
                "TAVILY_API_KEY": self.tavily_api_key,
            }
            missing = [name for name, value in required.items() if not str(value).strip()]
            if missing:
                raise ValueError(f"Production core services are not configured: {', '.join(missing)}")
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
