"""Хендлер /search — AI-поиск товаров в казахстанских магазинах через Tavily."""

from __future__ import annotations

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_settings
from bot.locales import t

router = Router(name="search")


@router.message(Command("search", "find"))
async def cmd_search(message: Message) -> None:
    """Поиск товаров в казахстанских магазинах через AI.

    Использование: /search офисный стул до 60 тысяч тенге
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            t("search_prompt", "ru"),
            parse_mode="Markdown",
        )
        return

    query = args[1].strip()
    wait = await message.answer(
        t("search_loading", "ru", query=query),
        parse_mode="Markdown",
    )

    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{s.backend_url}/products/search",
                json={
                    "query": query,
                    "additional_info": "Казахстан, казахстанские магазины",
                },
            )
        if resp.status_code != 200:
            await wait.edit_text(f"❌ Ошибка API: {resp.text[:500]}")
            return
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        await wait.edit_text(f"❌ Ошибка: {e}")
        return

    products = data.get("products", [])
    summary = data.get("summary", "")

    if not products:
        await wait.edit_text(
            f"🤷 По запросу *{query}* ничего не найдено.\n\n"
            "Попробуйте переформулировать или уточнить параметры.",
            parse_mode="Markdown",
        )
        return

    # Формируем ответ: топ-5 с ценами и кнопками
    lines = [f"🔍 *{query}*", ""]
    if summary:
        lines.append(f"_{summary}_")
        lines.append("")

    for i, p in enumerate(products, 1):
        name = p.get("name", "?")[:60]
        price = p.get("price_kzt")
        store = p.get("store", "")
        rating = p.get("rating")
        score = p.get("match_score", 0)
        reason = p.get("match_reason", "")[:100]
        url = p.get("url", "")

        score_emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        price_str = f"{price:,.0f} ₸" if price else "?"
        rating_str = f" ⭐{rating:.1f}" if rating else ""

        lines.append(
            f"{score_emoji} *{i}. [{name}]({url})*\n"
            f"   💰 {price_str} · 🏪 {store}{rating_str}\n"
            f"   _{reason}_"
        )
        lines.append("")

    lines.append("💡 _Нажми на название чтобы открыть товар_")

    await wait.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "search_more")
async def cb_search_more(cb: CallbackQuery) -> None:
    await cb.answer("Отправьте /search с новым запросом", show_alert=True)
