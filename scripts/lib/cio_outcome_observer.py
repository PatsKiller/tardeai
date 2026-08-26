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
        "recorded_at": datetime.now(timezone.utc).isoformat(),
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


def mature_deferred_by_age(*, horizon_days: int = 7, apply: bool = True) -> dict[str, Any]:
    """Mature DEFERRED dispositions older than horizon without inventing P&L.

    Marks matured_reason=EXPIRED_HORIZON. Does not flip MBI / eligible_runs.
    """
    proj = _cio_dir() / "cio_outcome_maturity.json"
    if not proj.is_file():
        return {"ok": True, "matured_expired": 0, "authority": AUTHORITY}
    try:
        mat = json.loads(proj.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "authority": AUTHORITY}
    items = dict(mat.get("items") or {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=horizon_days)
    n = 0
    for key, row in list(items.items()):
        if row.get("matured"):
            continue
        if str(row.get("disposition") or "").upper() != "DEFERRED":
            continue
        # Prefer matured_at placeholder / recorded_at; fall back to event store skip
        ts_raw = row.get("recorded_at") or row.get("matured_at") or row.get("updated_at")
        if not ts_raw:
            # no timestamp — do not invent overdue
            continue
        try:
            dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt > cutoff:
            continue
        n += 1
        if apply:
            row["matured"] = True
            row["matured_at"] = datetime.now(timezone.utc).isoformat()
            row["matured_reason"] = "EXPIRED_HORIZON"
            items[key] = row
    if apply and n:
        mat["items"] = items
        mat["matured_count"] = sum(1 for v in items.values() if v.get("matured"))
        mat["updated_at"] = datetime.now(timezone.utc).isoformat()
        mat["expired_horizon_matured"] = int(mat.get("expired_horizon_matured") or 0) + n
        proj.write_text(json.dumps(mat, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": True,
        "matured_expired": n,
        "applied": apply,
        "horizon_days": horizon_days,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
    }


def observe_expired_volume(*, apply: bool = False, horizon_days: int = 7) -> dict[str, Any]:
    """D1: combine production-case EXPIRED observer + deferred disposition aging."""
    case_obs: dict[str, Any] = {}
    try:
        try:
            from lib.intelligence_lineage import observe_overdue_cases
        except Exception:
            from scripts.lib.intelligence_lineage import observe_overdue_cases  # type: ignore
        case_obs = observe_overdue_cases(apply=apply, horizon_days=horizon_days)
    except Exception as exc:
        case_obs = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
    defer_obs = mature_deferred_by_age(horizon_days=horizon_days, apply=apply)
    return {
        "ok": True,
        "schema": "CIOExpiredMaturityObserve@v1",
        "cases": case_obs,
        "deferred_dispositions": defer_obs,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "eligible_runs": 0,
        "note": "EXPIRED = horizon elapsed without market P&L invention.",
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
            "expired_horizon_matured": 0,
            "authority": AUTHORITY,
            "note": "No matured outcomes yet — SHADOW influence remains.",
        }
    try:
        mat = json.loads(proj.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "authority": AUTHORITY}
    items = list((mat.get("items") or {}).values())
    expired_n = sum(1 for i in items if i.get("matured_reason") == "EXPIRED_HORIZON")
    return {
        "ok": True,
        "schema": mat.get("schema") or "CIOOutcomeMaturity@v1",
        "matured_count": int(mat.get("matured_count") or sum(1 for i in items if i.get("matured"))),
        "total_recorded": len(items),
        "expired_horizon_matured": int(mat.get("expired_horizon_matured") or expired_n),
        "items": items[-50:],
        "eligible_runs": int(mat.get("eligible_runs") or 0),
        "memory_behavior_influence": 0,
        "authority": AUTHORITY,
        "updated_at": mat.get("updated_at"),
        "note": "MBI remains 0 until eligible_runs proven non-zero under gate.",
    }
