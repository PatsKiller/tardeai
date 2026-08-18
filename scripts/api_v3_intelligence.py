"""GET-only Command Center APIs for IntelligenceLineage@v1.

READ_ONLY_ADVISORY. No broker/order/stop/risk/2FA mutation.
Never invents POSITIVE/NEGATIVE outcomes. Never deletes challenge history.
"""
from __future__ import annotations

from typing import Any

try:
    from lib import intelligence_lineage as L
except ImportError:
    from scripts.lib import intelligence_lineage as L  # type: ignore

AUTHORITY = {
    "authority": "READ_ONLY_ADVISORY",
    "mutation": False,
    "financial_action": False,
    "service_control": False,
    "provider_call": False,
    "auto_promotion_to_trading": False,
    "schema": L.SCHEMA,
}


def handle_get(path: str, query: dict | None = None) -> tuple[int, dict[str, Any]]:
    p = (path or "").strip("/")
    if p in ("", "closed-loop", "dashboard", "authority"):
        return 200, {**AUTHORITY, **L.summary()}
    if p == "challenges":
        return 200, {"ok": True, **AUTHORITY, **L.challenge_view()}
    if p in ("queue", "queue-health"):
        try:
            from lib.hermes_queue_health import build as queue_health
        except ImportError:
            from scripts.lib.hermes_queue_health import build as queue_health  # type: ignore
        return 200, {"ok": True, **AUTHORITY, **queue_health()}
    if p in ("circuit", "backend"):
        try:
            from lib.research_circuit import load as circuit_load
        except ImportError:
            from scripts.lib.research_circuit import load as circuit_load  # type: ignore
        return 200, {"ok": True, **AUTHORITY, **circuit_load()}
    if p == "reconciliation":
        try:
            from lib.cio_reconciliation import build as rec_build
        except ImportError:
            from scripts.lib.cio_reconciliation import build as rec_build  # type: ignore
        return 200, {"ok": True, **AUTHORITY, **rec_build()}
    if p in ("lineage", "lineages"):
        snap = L.load_snapshot()
        return 200, {
            "ok": True,
            **AUTHORITY,
            "count": snap.get("count") or 0,
            "by_status": snap.get("by_status") or {},
            "generated_at": snap.get("generated_at"),
            "lineages": snap.get("lineages") or [],
        }
    if p.startswith("lineage/"):
        lid = p.split("/", 1)[1].strip()
        rec = L.get_lineage(lid)
        if not rec:
            return 404, {"ok": False, **AUTHORITY, "error": "lineage_not_found", "lineage_id": lid}
        return 200, {"ok": True, **AUTHORITY, "lineage": rec}
    return 404, {"ok": False, **AUTHORITY, "error": f"unknown_intelligence_path: {p}"}
