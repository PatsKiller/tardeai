"""Canonical P0 containment for process_watchlist_agent_jobs (issue #283 / PR #284).

Single source of truth. While active, the worker must not run paid work and no
health/watchdog/remediation path may invoke the worker.

Activate by either:
  - env AGENT_JOBS_P0_CONTAINED=1|true|yes
  - flag file (default: ~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED)

Remediation callers must use guard_remediation_command() / report_contained().
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Canonical flag — one path, one env name
ENV_NAME = "AGENT_JOBS_P0_CONTAINED"
DEFAULT_FLAG = Path.home() / ".local" / "state" / "tradeai" / "AGENT_JOBS_P0_CONTAINED"
FLAG_PATH = Path(os.environ.get("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(DEFAULT_FLAG)))

WORKER_SCRIPT_MARKERS = (
    "process_watchlist_agent_jobs.py",
    "process_watchlist_agent_jobs",
)

CONTAINED_CODE = "CONTAINED"
CONTAINED_MESSAGE = (
    "CONTAINED: process_watchlist_agent_jobs is under P0 containment "
    "(issue #283). Remediation will not invoke the worker. "
    "Clear flag only after governed deploy + explicit re-enable approval."
)


def is_contained() -> bool:
    """True when P0 containment is active (env or flag file)."""
    raw = (os.environ.get(ENV_NAME) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    try:
        return FLAG_PATH.exists()
    except Exception:
        return False


def activate(reason: str = "p0") -> Path:
    """Create the flag file (host-side containment). Idempotent."""
    FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAG_PATH.write_text(f"active reason={reason}\n")
    return FLAG_PATH


def report_contained(*, source: str = "unknown") -> dict[str, Any]:
    return {
        "status": CONTAINED_CODE,
        "contained": True,
        "source": source,
        "message": CONTAINED_MESSAGE,
        "flag_path": str(FLAG_PATH),
        "env": ENV_NAME,
        "worker_invoked": False,
    }


def command_invokes_worker(cmd: str | None) -> bool:
    c = (cmd or "").lower()
    return any(m in c for m in WORKER_SCRIPT_MARKERS)


def guard_remediation_command(cmd: str | None, *, source: str = "health_agent") -> dict[str, Any]:
    """If containment active and cmd would run the worker, block and report CONTAINED."""
    if not command_invokes_worker(cmd):
        return {"blocked": False, "cmd": cmd, "contained": is_contained()}
    if is_contained():
        r = report_contained(source=source)
        r["blocked"] = True
        r["original_cmd"] = cmd
        r["cmd"] = None
        return r
    return {"blocked": False, "cmd": cmd, "contained": False}


def exit_if_contained_worker_entry() -> int | None:
    """Call at process_watchlist_agent_jobs __main__. Returns exit code if should stop."""
    if is_contained():
        print(CONTAINED_MESSAGE)
        return 78  # EX_CONFIG-ish: intentional non-zero, not a crash loop signal
    return None
