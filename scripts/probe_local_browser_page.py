"""Read a public Kaspi product page in an isolated headless browser."""

from __future__ import annotations

import asyncio
import argparse
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://kaspi.kz/shop/p/toplivnyi-fil-tr-13592436-108443317"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "docs" / "playwright-kaspi-probe-2026-10-07.json"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    report = {"url": args.url}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="ru-RU", viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            response = await page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            report["status"] = response.status if response else None
            await page.wait_for_timeout(3000)
            report["initial_title"] = await page.title()
            report["initial_text"] = (await page.locator("body").inner_text())[:5000]
            city = page.get_by_text("Астана", exact=True).first
            try:
                await city.click(timeout=5000)
                report["city_selected"] = True
                await page.wait_for_timeout(4000)
            except Exception as exc:
                report["city_selected"] = False
                report["city_error_type"] = type(exc).__name__
            text = await page.locator("body").inner_text()
            report["final_text"] = text[:10000]
            report["price_like"] = re.findall(r"\b[\d ]{3,12}\s*(?:₸|тг|тенге)\b", text)[:10]
            report["title"] = await page.title()
            try:
                await page.get_by_text("Характеристики", exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(1500)
                report["spec_text"] = (await page.locator("body").inner_text())[:10000]
                report["spec_tab_opened"] = True
            except Exception as exc:
                report["spec_tab_opened"] = False
                report["spec_error_type"] = type(exc).__name__
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error_summary"] = str(exc)[:200]
        finally:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({k: report.get(k) for k in ("status", "initial_title", "city_selected", "price_like", "spec_tab_opened", "error_type")}, ensure_ascii=False))
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
