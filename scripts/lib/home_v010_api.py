"""Home v010 read handlers (LQ-20261107-2149/2150). Thin and side-effect free: api_v2.py delegates here.

``diagnostics`` only READS the snapshot the ``home-diagnostics`` n8n lane wrote; it never probes the database, never
writes, and a snapshot older than the registry's ``max_snapshot_age_s`` grades every row UNKNOWN (COLLECTOR_STALE).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib import home_diagnostics as hd


_FALLBACK_WIDGET_IDS = ("action_unprotected_position", "action_approvals", "action_data_integrity", "validation_gates",
                        "since_last_visit", "status_portfolio", "status_orders", "status_schedulers", "status_alerts",
                        "status_data", "vix_market", "trade_ready", "details_deploys")


def _widget_ids() -> list:
    """Widget ids for the registry-invalid answer: read tolerantly from the thresholds file, else the 13 known ids."""
    try:
        ids = [w["widget_id"] for w in json.loads(hd.THRESHOLDS_PATH.read_text(encoding="utf-8"))["widgets"]]
        if ids:
            return ids
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return list(_FALLBACK_WIDGET_IDS)


def registry_view(now: Optional[datetime] = None) -> dict[str, Any]:
    """GET /api/v2/home/registry: the cause / owner / incident-class registry, read-only, for the diagnostics drawer."""
    now = now or datetime.now(timezone.utc)
    try:
        doc = json.loads(hd.REGISTRY_PATH.read_text(encoding="utf-8"))
        hd.validate_incident_registry(doc)
    except (OSError, ValueError, hd.RegistryError) as exc:
        return {"schema": "HomeStatusRegistry@v1", "state": "UNKNOWN", "reason": f"{type(exc).__name__}: {exc}"[:240],
                "served_at": now.isoformat()}
    return {"schema": doc["schema"], "state": "OK", "reason": None, "served_at": now.isoformat(),
            "version": doc.get("version"), "owners": doc["owners"], "causes": doc["causes"],
            "incident_classes": doc["incident_classes"], "unclassified_incident": doc["unclassified_incident"], "incident_classes_approved": doc["incident_classes_approved"],
            "requires_stop": doc["requires_stop"], "stop_exempt_accounts": doc["stop_exempt_accounts"]}


def diagnostics(state_dir: Path | str, now: Optional[datetime] = None, registry: Optional[dict] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    snap: Any = None
    try:
        snap = json.loads((Path(state_dir) / hd.SNAPSHOT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snap = None
    try:
        reg = registry or hd.load_registry()
    except (hd.RegistryError, OSError, ValueError) as exc:
        # An invalid registry still returns all 13 rows, each UNKNOWN / READ_FAILURE: zero rows would read as "nothing to show".
        reason = f"registry invalid: {type(exc).__name__}: {exc}"[:240]
        rows = [{"widget_id": wid, "widget": wid, "state": "UNKNOWN", "cause_category": "READ_FAILURE",
                 "cause": "The source exists but the read failed", "why": reason, "source_id": None,
                 "owner": "UNREGISTERED", "age_s": None, "needs_backend": None} for wid in _widget_ids()]
        return {"schema": hd.SCHEMA, "state": "UNKNOWN", "detail": "registry_invalid", "reason": reason,
                "served_at": now.isoformat(), "rows": rows}
    return hd.serve(snap, reg, now)
