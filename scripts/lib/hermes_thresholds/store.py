"""Persistence for learned thresholds, proposals, and audit trail."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CFG_PATH = PROJECT_ROOT / "config" / "hermes_thresholds.yaml"
ACTIVE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_thresholds.json"
PROPOSALS_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_threshold_proposals.json"
AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_threshold_audit.jsonl"


def load_threshold_config() -> dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def static_defaults(cfg: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """threshold_id -> {value, label, safe_band, max_step, path}."""
    cfg = cfg or load_threshold_config()
    out: dict[str, dict[str, Any]] = {}
    for tid, spec in (cfg.get("thresholds") or {}).items():
        out[tid] = {
            "value": float(spec.get("static_default", 0)),
            "label": spec.get("label", tid),
            "safe_band": spec.get("safe_band") or {},
            "max_step": float(spec.get("max_step", 0.03)),
            "min_step": float(spec.get("min_step", 0.01)),
            "path": spec.get("path") or [],
            "priority": spec.get("priority", "medium"),
        }
    return out


def load_active_thresholds() -> dict[str, Any]:
    """Active learned thresholds; empty shell if none approved yet."""
    if not ACTIVE_PATH.exists():
        return {"version": "thresholds-v1", "thresholds": {}, "history": []}
    try:
        return json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "thresholds-v1", "thresholds": {}, "history": []}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def save_active_thresholds(payload: dict[str, Any]) -> Path:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(ACTIVE_PATH, payload)
    return ACTIVE_PATH


def get_active_value(threshold_id: str, cfg: dict[str, Any] | None = None) -> float | None:
    """Resolved value: learned if approved, else static default."""
    defaults = static_defaults(cfg)
    active = load_active_thresholds()
    entry = (active.get("thresholds") or {}).get(threshold_id)
    if entry and entry.get("value") is not None:
        return float(entry["value"])
    d = defaults.get(threshold_id)
    return float(d["value"]) if d else None


def load_proposals() -> dict[str, Any]:
    if not PROPOSALS_PATH.exists():
        return {"version": "proposals-v1", "pending": [], "decided": []}
    try:
        return json.loads(PROPOSALS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "proposals-v1", "pending": [], "decided": []}


def save_proposals(payload: dict[str, Any]) -> Path:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(PROPOSALS_PATH, payload)
    return PROPOSALS_PATH


def append_audit(event: dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), **event}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def last_audit_event(action: str | None = None) -> dict[str, Any] | None:
    """Most recent audit row, optionally filtered by action."""
    if not AUDIT_PATH.exists():
        return None
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if action is None or row.get("action") == action:
            return row
    return None


def new_proposal_id() -> str:
    return f"tp_{uuid.uuid4().hex[:10]}"


def merge_learned_into_reactions(reactions_cfg: dict[str, Any]) -> dict[str, Any]:
    """Overlay approved learned thresholds onto reactions config dict."""
    cfg = load_threshold_config()
    if not cfg.get("learning", {}).get("enabled", True):
        return reactions_cfg

    rc = dict(reactions_cfg)
    defaults = static_defaults(cfg)
    active = load_active_thresholds().get("thresholds") or {}

    for tid, spec in defaults.items():
        path = spec.get("path") or []
        if len(path) < 2:
            continue
        entry = active.get(tid)
        if not entry or entry.get("value") is None:
            continue
        val = float(entry["value"])
        section, key = path[0], path[1]
        sec = dict(rc.get(section) or {})
        sec[key] = val
        sec["learned_threshold_id"] = tid
        sec["learned_at"] = entry.get("approved_at")
        rc[section] = sec

    rc["_learned_thresholds_applied"] = list(active.keys())
    return rc