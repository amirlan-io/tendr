"""Точка входа Telegram-бота."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from bot.config import get_settings
from bot.handlers import analyze, common, discover, incomplete, search, verify


async def main() -> None:
    s = get_settings()
    if not s.bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Fill .env first.")

    bot = Bot(
        token=s.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    dp.include_router(common.router)
    dp.include_router(discover.router)
    dp.include_router(incomplete.router)
    dp.include_router(search.router)
    dp.include_router(verify.router)
    dp.include_router(analyze.router)

    logger.info("Tendr bot starting…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
