"""Read-only probe: compare Tavily order with AnyModel rerank for supplier search."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from tavily import TavilyClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings

QUERIES = [
    "Стол офисный 1400х700 мм ЛДСП 25 мм металлический каркас Казахстан",
    "Регулятор давления стальной фланцевый Ду80 60,3 МПа Казахстан",
]
RERANK_MODEL = "am/llama-nemotron-rerank-vl-1b-v2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.tavily_api_key:
        raise RuntimeError("Tavily is not configured")
    key = args.api_key_file.read_text().strip()
    tavily = TavilyClient(api_key=settings.tavily_api_key)
    report = {"purpose": "search ranking probe, not a product compliance check", "rerank_model": RERANK_MODEL, "queries": []}
    with httpx.Client(timeout=45) as http:
        for query in QUERIES:
            search = tavily.search(query=query, search_depth="advanced", max_results=10)
            rows = [{"title": str(item.get("title") or "")[:200],
                     "url": str(item.get("url") or ""),
                     "snippet": str(item.get("content") or "")[:900],
                     "search_score": item.get("score")}
                    for item in search.get("results", [])]
            payload = {"model": RERANK_MODEL, "query": query,
                       "documents": [f"{row['title']}\n{row['snippet']}" for row in rows],
                       "top_n": len(rows), "return_documents": False}
            response = http.post("https://anymodel.org/v1/rerank",
                                 headers={"Authorization": "Bearer " + key}, json=payload)
            response.raise_for_status()
            rank = response.json().get("results", [])
            for position, match in enumerate(rank, 1):
                index = match.get("index")
                if isinstance(index, int) and 0 <= index < len(rows):
                    rows[index]["rerank_position"] = position
                    rows[index]["rerank_score"] = match.get("relevance_score")
            report["queries"].append({"query": query, "rows": rows})
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({"query": query, "original_top": [r["title"] for r in rows[:3]],
                              "reranked_top": [r["title"] for r in sorted(rows, key=lambda r: r.get("rerank_position", 999))[:3]]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
