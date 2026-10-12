"""Offline evaluation of saved live search results; spends no API credits."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.supplier_agent import (  # noqa: E402
    Requirement, evidence_coverage, rank_results_for_requirement,
    search_query_pair, source_page_rank,
)
from app.core.config import get_settings  # noqa: E402


def main() -> None:
    saved = json.loads((ROOT / "docs/regulator-one-query-2026-10-07.json").read_text())
    baseline = json.loads((ROOT / "docs/kaspi-agent-sandbox-without-laptop-2026-10-07.json").read_text())
    requirement = Requirement(
        "regulator", "Регулятор давления",
        "Стальной, фланцевый, проход 80 мм, давление 60,3 МПа. Количество 1 шт.",
    )
    ranked = rank_results_for_requirement(saved["results"], requirement)
    assessments = []
    for item in ranked:
        found, total = evidence_coverage(
            requirement, item["title"] + " " + item["content"]
        )
        assessments.append({"url": item["url"], "hints_found": found,
                            "hints_total": total, "source_rank": source_page_rank(item["url"])})
    report = {
        "mode": "offline replay of one live basic search; no API calls",
        "previous_full_sandbox_tavily_calls": baseline["runs"][0]["result"]["costs"]["tavily_calls"],
        "current_call_limit": get_settings().supplier_search_max_calls,
        "regulator_queries": search_query_pair(requirement),
        "live_results_seen": len(saved["results"]),
        "relevant_results_kept": len(ranked),
        "fully_verified_from_snippets": sum(a["hints_found"] == a["hints_total"] for a in assessments),
        "assessments": assessments,
    }
    path = ROOT / "docs/supplier-search-offline-eval-2026-10-07.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: report[key] for key in (
        "previous_full_sandbox_tavily_calls", "current_call_limit",
        "live_results_seen", "relevant_results_kept", "fully_verified_from_snippets",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
