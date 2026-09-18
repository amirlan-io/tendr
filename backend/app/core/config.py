"""Центральный конфиг приложения. Загружается из .env через pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Общее ===
    app_env: Literal["dev", "prod"] = "dev"
    app_name: str = "tendr"
    default_lang: Literal["ru", "kk"] = "ru"
    log_level: str = "INFO"

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

    # === Security ===
    max_upload_bytes: int = 20 * 1024 * 1024
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

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x) for x in self.admin_telegram_ids.split(",") if x.strip().isdigit()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
