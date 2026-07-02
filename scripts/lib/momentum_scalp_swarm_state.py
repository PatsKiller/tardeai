"""momentum_scalp_swarm_state.py — atomic read/write for Multi-Hermes scalp swarm shared state.

State root: state/momentum_scalp/ (see docs/hermes/momentum_scalp_swarm/SHARED_STATE_SCHEMA.md)
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_ROOT = PROJECT_ROOT / "state" / "momentum_scalp"

STATE_FILES = (
    "open_scalps.json",
    "portfolio_heat.json",
    "regime_state.json",
    "stoplight_status.json",
    "stop_adjustment_history.json",
    "validation_tracker.json",
    "orchestrator_audit.json",
    "pending_approvals.json",
    "qualified_signals.json",
    "entry_validation_queue.json",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_path(name: str) -> Path:
    return STATE_ROOT / f".{name}.lock"


@contextmanager
def file_lock(name: str, timeout_s: float = 5.0):
    """Simple exclusive lock via O_EXCL create; stale locks expire after timeout."""
    lp = _lock_path(name)
    lp.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            try:
                yield
            finally:
                try:
                    lp.unlink(missing_ok=True)
                except OSError:
                    pass
            return
        except FileExistsError:
            try:
                if lp.exists() and (time.time() - lp.stat().st_mtime) > timeout_s * 2:
                    lp.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.05)
    raise TimeoutError(f"lock timeout: {name}")


def read_json(name: str, default: Any = None) -> Any:
    p = STATE_ROOT / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(name: str, data: Any) -> None:
    p = STATE_ROOT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with file_lock(name):
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(p)


def append_audit(event: dict) -> None:
    """Append one orchestrator audit entry (bounded to 500 events)."""
    with file_lock("orchestrator_audit"):
        log = read_json("orchestrator_audit.json", {"events": []}) or {"events": []}
        events = list(log.get("events") or [])
        events.append({**event, "ts": event.get("ts") or now_iso()})
        log["events"] = events[-500:]
        log["updated_at"] = now_iso()
        p = STATE_ROOT / "orchestrator_audit.json"
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(log, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(p)


def state_health() -> dict:
    """Summary for /api/v2/hermes/scalp-swarm/status."""
    out: dict[str, Any] = {"state_root": str(STATE_ROOT), "files": {}, "updated_at": now_iso()}
    for name in STATE_FILES:
        p = STATE_ROOT / name
        if not p.exists():
            out["files"][name] = {"exists": False}
            continue
        age_h = (time.time() - p.stat().st_mtime) / 3600.0
        out["files"][name] = {
            "exists": True,
            "age_hours": round(age_h, 2),
            "size_bytes": p.stat().st_size,
        }
    return out