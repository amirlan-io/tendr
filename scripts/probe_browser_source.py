"""Read-only smoke test for the configured Browser-Use fallback on one public card."""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.browser_use import BrowserUseAgent
from app.core.config import get_settings

URL = "https://kaspi.kz/shop/p/toplivnyi-fil-tr-13592436-108443317"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="browser-use-2.0")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "browser-source-probe-2026-10-07.json")
    args = parser.parse_args()
    key = get_settings().browser_use_api_key
    if not key:
        raise RuntimeError("Browser-Use is not configured")
    agent = BrowserUseAgent(api_key=key)
    report = {"url": URL, "model": args.model, "task": "read a public product card; no login or purchase"}
    try:
        result = await asyncio.wait_for(agent.run_task(
            task=(f"Открой только публичную карточку {URL}. Найди точное название товара, "
                  "цену в тенге, характеристики, наличие и сведения о гарантии. "
                  "Верни JSON. Не входи в аккаунт, не оформляй заказ, не вводи данные."),
            model=args.model, proxy_country="kz", allowed_domains=["kaspi.kz"],
            enable_recording=False, max_duration_min=2,
        ), timeout=150)
        report.update({"status": result.status, "duration_sec": result.duration_sec,
                       "cost_usd": result.cost_usd, "output": result.output})
    except Exception as exc:
        report.update({"error_type": type(exc).__name__,
                       "error_summary": str(exc).replace(key, "[redacted]")[:220]})
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k: report.get(k) for k in ("status", "duration_sec", "cost_usd", "error_type", "error_summary")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
