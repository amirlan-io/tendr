"""Команды /start, /help, /lang и базовые кallback'и."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import language_choose, main_menu
from bot.locales import t

router = Router(name="common")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        t("start", "ru"),
        reply_markup=main_menu("ru"),
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(t("help", "ru"), parse_mode="Markdown")


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery) -> None:
    await cb.message.answer(t("help", "ru"), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "lang")
async def cb_lang(cb: CallbackQuery) -> None:
    await cb.message.edit_text(t("lang_choose", "ru"), reply_markup=language_choose())
    await cb.answer()


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang_set(cb: CallbackQuery) -> None:
    lang = cb.data.split(":", 1)[1]  # type: ignore[union-attr]
    if lang not in {"ru", "kk"}:
        await cb.answer()
        return
    await cb.message.edit_text(
        t("start", lang), reply_markup=main_menu(lang), parse_mode="Markdown"
    )
    await cb.answer()
