"""Конфиг бота — общий с бэкендом через .env в корне."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",  # бот лежит в tendr/bot/, env — в tendr/
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = ""
    backend_url: str = "http://localhost:8000"
    default_lang: str = "ru"
    admin_telegram_ids: str = ""


@lru_cache(maxsize=1)
def get_settings() -> BotSettings:
    return BotSettings()
