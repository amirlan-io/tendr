"""Клавиатуры бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text={"ru": "🔍 Анализ по ссылке", "kk": "🔍 Сілтеме бойынша талдау"}.get(
                lang, "🔍"
            ),
            callback_data="analyze_url",
        )
    )
    kb.row(
        InlineKeyboardButton(
            text={"ru": "🆕 Свежие лоты", "kk": "🆕 Жаңа лоттар"}.get(lang, "🆕"),
            callback_data="discover",
        ),
        InlineKeyboardButton(
            text={"ru": "🔔 Подписки", "kk": "🔔 Жазылу"}.get(lang, "🔔"),
            callback_data="subscriptions",
        ),
    )
    kb.row(
        InlineKeyboardButton(
            text={"ru": "ℹ️ Помощь", "kk": "ℹ️ Көмек"}.get(lang, "ℹ️"),
            callback_data="help",
        ),
        InlineKeyboardButton(
            text={"ru": "🌐 Язык", "kk": "🌐 Тіл"}.get(lang, "🌐"),
            callback_data="lang",
        ),
    )
    return kb.as_markup()


def language_choose() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="lang:kk"),
    )
    return kb.as_markup()
