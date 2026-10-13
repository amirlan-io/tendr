"""One tariff catalog shared by API, quota enforcement and the web build."""

import json
from pathlib import Path

PLAN_CATALOG = json.loads(Path(__file__).with_name("plans.json").read_text(encoding="utf-8"))
WINDOW_HOURS = 5

# Trial exposes the available workflows within its small common allowance.
PREVIEW_PLANS = {"free", "pilot"}


def capabilities_for(plan: str) -> set[str]:
    if plan in PREVIEW_PLANS:
        return set(PLAN_CATALOG["ultra"]["capabilities"])
    if plan == "monthly":
        plan = "pro"
    return set(PLAN_CATALOG.get(plan, {}).get("capabilities", []))
