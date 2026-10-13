"""Хендлер discovery: свежие лоты и подписки по ключевым словам."""

from __future__ import annotations

import urllib.parse

import httpx
from bot.http_client import BotApiClient
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.keyboards import main_menu
from bot.locales import t

router = Router(name="discover")


class SubscribeFSM(StatesGroup):
    waiting_keywords = State()


def _get_lang(state: FSMContext | None) -> str:
    return "ru"  # пока всегда ru


@router.message(Command("discover", "lots", "fresh"))
async def cmd_discover(message: Message) -> None:
    """Свежие лоты с goszakup.gov.kz."""
    lang = _get_lang(None)
    s = get_settings()
    wait = await message.answer(t("discover_loading", lang))

    try:
        async with BotApiClient(telegram_id=message.from_user.id if message.from_user else 0, timeout=30) as client:
            resp = await client.get(
                f"{s.backend_url}/discovery/feed", params={"max_pages": 2}
            )
        if resp.status_code != 200:
            await wait.edit_text(t("error", lang, error="Сервис временно недоступен или запрос отклонён."))
            return
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        await wait.edit_text(t("error", lang, error=str(e)))
        return

    items = data.get("items", [])
    if not items:
        await wait.edit_text(t("discover_empty", lang), parse_mode="Markdown")
        return

    text = t("discover_header", lang, count=len(items))
    for it in items[:10]:
        title = it["title"][:90]
        customer = it["customer"][:80]
        lot_id = it["lot_id"]
        text += f"\n\n🔹 *{title}*\n_{customer}_\n`{lot_id}`"

    await wait.edit_text(
        text + "\n\n" + t("discover_hint", lang),
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )


@router.callback_query(F.data == "discover")
async def cb_discover(cb: CallbackQuery) -> None:
    await cb.message.answer(t("discover_loading", "ru"))
    await cmd_discover(cb.message)  # type: ignore[arg-type]
    await cb.answer()


@router.message(Command("subscribe", "sub"))
async def cmd_subscribe(message: Message, state: FSMContext) -> None:
    """Запуск FSM для подписки на ключевые слова."""
    await state.set_state(SubscribeFSM.waiting_keywords)
    await message.answer(
        t("subscribe_prompt", "ru"),
        parse_mode="Markdown",
        reply_markup=main_menu("ru"),
    )


@router.callback_query(F.data == "subscriptions")
async def cb_subscriptions(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SubscribeFSM.waiting_keywords)
    await cb.message.answer(
        t("subscribe_prompt", "ru"),
        parse_mode="Markdown",
        reply_markup=main_menu("ru"),
    )
    await cb.answer()


@router.message(SubscribeFSM.waiting_keywords)
async def fsm_keywords(message: Message, state: FSMContext) -> None:
    """Получили ключевые слова — создаём подписку."""
    lang = _get_lang(state)
    if not message.text:
        await message.answer(t("error", lang, error="Пришлите текстом ключевые слова"))
        return
    s = get_settings()
    try:
        async with BotApiClient(telegram_id=message.from_user.id if message.from_user else 0, timeout=15) as client:
            resp = await client.post(
                f"{s.backend_url}/account/discovery/subscribe",
                json={"keywords": message.text.strip(), "channel": "telegram"},
                params={"user_id": message.from_user.id if message.from_user else 0},
            )
        if resp.status_code != 200:
            await message.answer(t("error", lang, error="Сервис временно недоступен или запрос отклонён."))
            return
    except Exception as e:  # noqa: BLE001
        await message.answer(t("error", lang, error=str(e)))
        return
    finally:
        await state.clear()

    await message.answer(
        t("subscribe_done", lang, keywords=message.text.strip()),
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )
