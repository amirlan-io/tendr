"""Compare public HTML search results without using Tavily credits."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    "регулятор давления стальной фланцевый 80 мм 60,3 МПа",
    "регулятор давления Ду80 фланцевый купить Казахстан",
    "топливный фильтр Chevrolet Cobalt 13592436 Казахстан",
]


def main() -> None:
    report = {"provider": "DuckDuckGo Lite public HTML", "uses_tavily_credits": False, "queries": []}
    for query in QUERIES:
        row = {"query": query, "results": []}
        try:
            response = httpx.get(
                "https://lite.duckduckgo.com/lite/", params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12,
            )
            row["status"] = response.status_code
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "lxml")
                for anchor in soup.select("a.result-link")[:10]:
                    link = anchor.get("href") or ""
                    if link.startswith("//"):
                        link = "https:" + link
                    url = parse_qs(urlsplit(link).query).get("uddg", [""])[0]
                    if url.startswith("https://") or url.startswith("http://"):
                        row["results"].append({"title": anchor.get_text(" ", strip=True), "url": url})
        except Exception as exc:
            row["error_type"] = type(exc).__name__
        report["queries"].append(row)
    path = ROOT / "docs/free-search-probe-2026-10-07.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps([{"query": r["query"], "status": r.get("status"),
                       "count": len(r["results"])} for r in report["queries"]], ensure_ascii=False))


if __name__ == "__main__":
    main()
