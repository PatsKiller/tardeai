"""Thin outcome observer for CIO dispositions → matured learning counts.

READ_ONLY_ADVISORY. MBI stays 0 until eligible_runs proven separately.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"

_DISP_MAP = {
    "ack": "ACKNOWLEDGED",
    "acknowledged": "ACKNOWLEDGED",
    "accept": "ACCEPTED",
    "accepted": "ACCEPTED",
    "defer": "DEFERRED",
    "deferred": "DEFERRED",
    "reject": "REJECTED",
    "rejected": "REJECTED",
    "done": "DONE",
    "cancel": "CANCELLED",
    "cancelled": "CANCELLED",
}

_MATURE_NOW = frozenset({"DONE", "ACKNOWLEDGED", "ACCEPTED", "REJECTED"})


def _cio_dir() -> Path:
    env = os.environ.get("TRADEAI_CIO_DIR")
    if env:
        return Path(env)
    return Path("data/cio")


def _store_path() -> Path:
    return _cio_dir() / "cio_outcomes.jsonl"


def record_disposition_outcome(
    *,
    decision_or_plan_id: str,
    disposition: str,
    lineage_id: str | None = None,
    rating: int | None = None,
    note: str = "",
    symbol: str | None = None,
) -> dict[str, Any]:
    """Append outcome via CIOOutcomeStore. Fail-soft."""
    try:
        from scripts.lib.cio_outcome_store import CIOOutcomeStore
    except Exception:
        from lib.cio_outcome_store import CIOOutcomeStore  # type: ignore

    disp = _DISP_MAP.get(str(disposition or "").strip().lower(), "")
    if not disp:
        return {"ok": False, "error": "invalid_disposition", "authority": AUTHORITY}

    matured = disp in _MATURE_NOW
    refs = []
    if lineage_id:
        refs.append(f"lineage:{lineage_id}")
    if symbol:
        refs.append(f"symbol:{symbol.upper()}")
    if rating is not None:
        refs.append(f"rating:{int(rating)}")

    store = CIOOutcomeStore(store_path=str(_store_path()))
    ev = store.record_outcome(
        cio_action_id=str(decision_or_plan_id),
        operator_disposition=disp,
        outcome_status="UNKNOWN",
        measurement_window="disposition_immediate" if matured else "deferred_window",
        context_refs=refs,
        result_summary=(note or "")[:400],
        what_was_right=f"operator_rating={rating}" if rating else "",
        actor="cio_outcome_observer",
    )
    # Side projection for learning API (maturity flag)
    proj = _cio_dir() / "cio_outcome_maturity.json"
    mat = {"items": {}, "updated_at": datetime.now(timezone.utc).isoformat()}
    if proj.is_file():
        try:
            mat = json.loads(proj.read_text(encoding="utf-8"))
        except Exception:
            pass
    items = dict(mat.get("items") or {})
    items[str(decision_or_plan_id)] = {
        "disposition": disp,
        "matured": matured,
        "matured_at": datetime.now(timezone.utc).isoformat() if matured else None,
        "lineage_id": lineage_id,
        "rating": rating,
        "event_id": ev.get("event_id"),
        "authority": AUTHORITY,
    }
    mat = {
        "schema": "CIOOutcomeMaturity@v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "matured_count": sum(1 for v in items.values() if v.get("matured")),
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "eligible_runs": 0,
    }
    proj.parent.mkdir(parents=True, exist_ok=True)
    proj.write_text(json.dumps(mat, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": True,
        "event_id": ev.get("event_id"),
        "matured": matured,
        "disposition": disp,
        "lineage_id": lineage_id,
        "authority": AUTHORITY,
    }


def learning_summary() -> dict[str, Any]:
    """GET payload for /api/v3/maturity/learning — fail-soft empty."""
    proj = _cio_dir() / "cio_outcome_maturity.json"
    if not proj.is_file():
        return {
            "ok": True,
            "schema": "CIOOutcomeMaturity@v1",
            "matured_count": 0,
            "items": [],
            "eligible_runs": 0,
            "memory_behavior_influence": 0,
            "authority": AUTHORITY,
            "note": "No matured outcomes yet — SHADOW influence remains.",
        }
    try:
        mat = json.loads(proj.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "authority": AUTHORITY}
    items = list((mat.get("items") or {}).values())
    return {
        "ok": True,
        "schema": mat.get("schema") or "CIOOutcomeMaturity@v1",
        "matured_count": int(mat.get("matured_count") or sum(1 for i in items if i.get("matured"))),
        "total_recorded": len(items),
        "items": items[-50:],
        "eligible_runs": int(mat.get("eligible_runs") or 0),
        "memory_behavior_influence": 0,
        "authority": AUTHORITY,
        "updated_at": mat.get("updated_at"),
        "note": "MBI remains 0 until eligible_runs proven non-zero under gate.",
    }
