"""Хендлер /verify — Browser-Use проверка цен на сайтах поставщиков.

Использование:
    /verify наушники Sony
    /verify ноутбук Lenovo до 300000
"""

from __future__ import annotations

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import get_settings

router = Router(name="verify")


@router.message(Command("verify"))
async def cmd_verify(message: Message) -> None:
    """Поиск товаров + ИИ-проверка реальных цен на сайтах через Browser-Use.

    Отличия от /search:
      /search — быстро (Tavily, ~3-5 сек), но цены могут быть устаревшими.
      /verify — медленно (Browser-Use, ~60-120 сек), но ИИ реально заходит
                 на сайт поставщика и проверяет актуальную цену.

    Стоимость: ~$0.10-0.30 за запрос (проверяет топ-3 товара).
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "🤖 *Browser-Use: проверка цен на сайтах*\n\n"
            "Использование: `/verify <запрос>`\n\n"
            "Примеры:\n"
            "• `/verify наушники Sony`\n"
            "• `/verify ноутбук Lenovo до 300000`\n"
            "• `/verify МФУ для офиса`\n\n"
            "Что делает:\n"
            "1. Tavily находит ссылки на kaspi.kz, sulpak.kz, technodom.kz\n"
            "2. AI фильтрует топ-3\n"
            "3. ИИ-агент заходит на сайт и проверяет реальную цену\n"
            "4. Возвращает подтверждённые цены\n\n"
            "⏱ Занимает 1-2 минуты, ~$0.10-0.30",
            parse_mode="Markdown",
        )
        return

    query = args[1].strip()
    wait = await message.answer(
        f"🤖 *Запускаю ИИ-агента...*\n\n"
        f"Запрос: _{query}_\n"
        f"Этапы:\n"
        f"1️⃣ Tavily → поиск ссылок (5-10 сек)\n"
        f"2️⃣ AI → фильтр топ-3 (5-10 сек)\n"
        f"3️⃣ Browser-Use → проверка цен на сайтах (60-120 сек)\n\n"
        f"⏳ Ожидайте ~1-2 минуты...",
        parse_mode="Markdown",
    )

    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=240) as client:
            resp = await client.post(
                f"{s.backend_url}/products/search",
                json={
                    "query": query,
                    "additional_info": "Казахстан, казахстанские магазины",
                    "browser_action": "verify_price",
                    "browser_model": "gpt-5.4-mini",
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
    browser_actions = data.get("browser_actions_count", 0)
    browser_cost = data.get("browser_total_cost_usd", 0.0)
    browser_duration = data.get("browser_total_duration_sec", 0.0)

    if not products:
        await wait.edit_text(
            f"🤷 По запросу *{query}* ничего не найдено.",
            parse_mode="Markdown",
        )
        return

    lines = [
        f"🤖 *{query}* (проверено ИИ в браузере)",
        "",
    ]
    if summary:
        lines.append(f"_{summary}_")
        lines.append("")

    for i, p in enumerate(products, 1):
        name = p.get("name", "?")[:60]
        price_tavily = p.get("price_kzt")
        price_browser = p.get("browser_verified_price")
        store = p.get("store", "")
        rating = p.get("rating")
        score = p.get("match_score", 0)
        reason = p.get("match_reason", "")[:100]
        url = p.get("url", "")
        recording = p.get("browser_recording_url")

        score_emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
        rating_str = f" ⭐{rating:.1f}" if rating else ""

        # Цена
        if price_browser and price_tavily and abs(price_browser - price_tavily) > 100:
            # Цена изменилась
            direction = "📉 дешевле" if price_browser < price_tavily else "📈 дороже"
            price_line = f"   💰 ~~{price_tavily:,.0f} ₸~~ → *{price_browser:,.0f} ₸* {direction} 🤖\n"
        elif price_browser:
            price_line = f"   💰 *{price_browser:,.0f} ₸* 🤖 (подтверждено)\n"
        elif price_tavily:
            price_line = f"   💰 {price_tavily:,.0f} ₸ (Tavily)\n"
        else:
            price_line = "   💰 ?\n"

        lines.append(
            f"{score_emoji} *{i}. [{name}]({url})*\n"
            f"   🏪 {store}{rating_str}\n"
            f"{price_line}"
            f"   _{reason}_"
        )
        if recording:
            lines.append(f"   🎥 [Видео проверки]({recording})")
        lines.append("")

    if browser_actions > 0:
        lines.extend(
            [
                "─" * 30,
                f"🤖 Browser-Use: {browser_actions} сайтов проверено",
                f"💰 Стоимость: ${browser_cost:.3f}",
                f"⏱ Время: {browser_duration:.0f}s",
                "🎥 Видео живёт 1 час",
            ]
        )

    await wait.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@router.message(Command("verifycontacts"))
async def cmd_verify_contacts(message: Message) -> None:
    """Найти контакты поставщика (email, телефон, БИН) через Browser-Use."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📞 *Контакты поставщика через ИИ-агента*\n\n"
            "Использование: `/verifycontacts <товар или сайт>`\n\n"
            "Пример:\n"
            "• `/verifycontacts канцелярские товары Алматы`\n"
            "• `/verifycontacts мебель для офиса`",
            parse_mode="Markdown",
        )
        return

    query = args[1].strip()
    wait = await message.answer(
        f"📞 Ищу контакты поставщиков по запросу _{query}_...\n"
        f"Это займёт ~1-2 минуты...",
        parse_mode="Markdown",
    )

    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=240) as client:
            resp = await client.post(
                f"{s.backend_url}/products/search",
                json={
                    "query": query,
                    "additional_info": "Казахстан, оптовые поставщики",
                    "browser_action": "extract_contacts",
                    "browser_model": "gpt-5.4-mini",
                },
            )
        if resp.status_code != 200:
            await wait.edit_text(f"❌ Ошибка: {resp.text[:500]}")
            return
        data = resp.json()
    except Exception as e:
        await wait.edit_text(f"❌ Ошибка: {e}")
        return

    products = data.get("products", [])
    if not products:
        await wait.edit_text(f"🤷 По запросу *{query}* ничего не найдено.")
        return

    lines = [f"📞 *{query}* — контакты поставщиков", ""]
    for i, p in enumerate(products, 1):
        name = p.get("name", "?")[:50]
        url = p.get("url", "")
        concerns = p.get("concerns", [])

        # Извлекаем контакты из concerns (формат: 📧 Email: ..., 📞 Тел: ...)
        contacts = [c for c in concerns if c.startswith("📧") or c.startswith("📞")]

        if contacts:
            lines.append(f"*{i}. [{name}]({url})*")
            for c in contacts:
                lines.append(f"   {c}")
            lines.append("")
        else:
            lines.append(f"*{i}. [{name}]({url})*")
            lines.append("   _Контакты не найдены автоматически — открой сайт вручную_")
            lines.append("")

    browser_actions = data.get("browser_actions_count", 0)
    if browser_actions > 0:
        lines.extend(
            [
                "─" * 30,
                f"🤖 Проверено: {browser_actions} сайтов",
                f"💰 Стоимость: ${data.get('browser_total_cost_usd', 0):.3f}",
            ]
        )

    await wait.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
