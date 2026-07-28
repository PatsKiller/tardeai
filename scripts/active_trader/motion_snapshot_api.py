"""Read-only projection of the latest aggregate Active Trader motion snapshot."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .motion_engine import CONTRACT, default_snapshot_path

_ZERO_AUTHORITY = {
    "mutation": False,
    "order": False,
    "session_authorize": False,
    "canary": False,
    "financial_action": False,
    "auto_exit": False,
}


def _timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


def _empty(state: str, detail: str, *, now: float) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "generated_at": None,
        "served_at": now,
        "data_state": state,
        "available": False,
        "ui_refresh_after_s": 30,
        "push_primary": True,
        "max_pull_fallbacks_per_minute": 2,
        "t2": {
            "operating_cap": 2,
            "provider_hard_cap": 8,
            "leases": [],
            "decisions": [],
            "events": [],
        },
        "candidates": [],
        "positions": [],
        "exit_signals": [],
        "authority": dict(_ZERO_AUTHORITY),
        "detail": detail,
        "read_only": True,
        "write": False,
    }


def read_motion_snapshot(
    path: str | Path | None = None,
    *,
    now: float | None = None,
    stale_after_s: float | None = None,
) -> dict[str, Any]:
    now = float(time.time() if now is None else now)
    if stale_after_s is None:
        try:
            stale_after_s = float(os.environ.get("ACTIVE_TRADER_MOTION_STALE_AFTER_S", "35"))
        except ValueError:
            stale_after_s = 35.0
    stale_after_s = max(5.0, float(stale_after_s))
    snapshot_path = Path(path).expanduser() if path else default_snapshot_path()

    if not snapshot_path.is_file():
        return _empty("MOTION_API_UNAVAILABLE", "motion snapshot has not been produced", now=now)
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return _empty("MOTION_API_UNAVAILABLE", "motion snapshot is unreadable", now=now)
    if not isinstance(raw, Mapping) or raw.get("contract") != CONTRACT:
        return _empty("MOTION_API_UNAVAILABLE", "motion snapshot contract mismatch", now=now)

    body = dict(raw)
    generated_at = _timestamp(body.get("generated_at"))
    age = max(0.0, now - generated_at) if generated_at is not None else None
    body["served_at"] = now
    body["snapshot_age_s"] = age
    body["read_only"] = True
    body["write"] = False
    body["authority"] = dict(_ZERO_AUTHORITY)
    body["available"] = True
    if age is None or age > stale_after_s:
        body["data_state"] = "MOTION_DATA_STALE"
        body["detail"] = "last good motion snapshot is stale"
    else:
        body["data_state"] = str(body.get("data_state") or "LIVE_MOTION")
    try:
        refresh = int(body.get("ui_refresh_after_s") or 30)
    except (TypeError, ValueError):
        refresh = 30
    body["ui_refresh_after_s"] = min(30, max(5, refresh))
    return body
