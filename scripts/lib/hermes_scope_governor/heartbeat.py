"""Heartbeat files for cron health monitoring (not silent skips)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

GOVERNOR_HEARTBEAT = PROJECT_ROOT / "data" / "runtime" / "hermes_scope_governor_heartbeat.json"
FEEDER_HEARTBEAT = PROJECT_ROOT / "data" / "runtime" / "hermes_event_feeder_heartbeat.json"


def write_heartbeat(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def read_heartbeat(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def heartbeat_age_minutes(path: Path) -> float | None:
    hb = read_heartbeat(path)
    if not hb or not hb.get("ts"):
        return None
    try:
        dt = datetime.fromisoformat(str(hb["ts"]).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
    except Exception:
        return None