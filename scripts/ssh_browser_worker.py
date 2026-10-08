"""Kaspi product reader for an isolated SSH browser host; JSON on stdin/stdout."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from urllib.parse import urlsplit

from playwright.async_api import async_playwright


def supported(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "https" and parts.hostname == "kaspi.kz"
            and port in (None, 443) and not parts.username
            and not parts.password and parts.path.startswith("/shop/p/"))


def same_product_page(requested: str, loaded: str) -> bool:
    return (supported(requested) and supported(loaded)
            and urlsplit(requested).path.rstrip("/") == urlsplit(loaded).path.rstrip("/"))


async def read(url: str, city: str) -> dict:
    if not supported(url):
        raise ValueError("unsupported URL")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(locale="ru-RU")
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            if response is None or response.status != 200 or not same_product_page(url, page.url):
                raise ValueError("product page unavailable")
            await page.wait_for_timeout(1500)
            if city and re.fullmatch(r"[А-Яа-яЁё -]{2,40}", city):
                await page.get_by_text(city, exact=True).first.click(timeout=6000)
                await page.wait_for_timeout(2000)
            body = await page.locator("body").inner_text()
            match_city = re.search(r"Мой город:\s*\n\s*([^\n]+)", body)
            actual_city = match_city.group(1).strip() if match_city else ""
            if city and actual_city.casefold() != city.casefold():
                raise ValueError("requested city not selected")
            if not same_product_page(url, page.url):
                raise ValueError("product page changed")
            match_title = re.search(r"Код товара:\s*\d+\s*\n([^\n]+)", body)
            match_price = re.search(r"(?m)^Цена\s*\n\s*([\d\s\u00a0]+)\s*₸", body)
            if not match_title:
                raise ValueError("product title missing")
            price = int(re.sub(r"\D", "", match_price.group(1))) if match_price else None
            spec = ""
            try:
                await page.get_by_text("Характеристики", exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(1000)
                spec_body = await page.locator("body").inner_text()
                # Only the active specification section belongs to this product.
                start = spec_body.find("Характеристики\n")
                if start >= 0:
                    spec = spec_body[start:start + 5000]
                    spec = spec.split("Продукты Kaspi.kz", 1)[0]
            except Exception:
                pass
            return {
                "url": url, "product_title": match_title.group(1).strip(),
                "city": actual_city, "price_kzt": price,
                "evidence_text": (body[:body.find("Продавцы")] if "Продавцы" in body else body[:2500]) + "\n" + spec,
            }
        finally:
            await browser.close()


def main() -> None:
    try:
        request = json.loads(sys.stdin.buffer.readline())
        result = asyncio.run(read(str(request.get("url", "")), str(request.get("city", ""))))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)[:120]}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
