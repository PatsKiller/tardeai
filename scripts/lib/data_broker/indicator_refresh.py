# DEPRECATED 2026-08-06: No known consumers.
# Scheduled for removal. See Wave B/C Data Broker compliance remediation.
"""Data Broker — refresh indicator_confluence_cache + invalidate broker snapshot.

Single write path for RSI/SMA/MACD consumers (Watch MAIN desk, Re-Entry desk,
health agent, portfolio overlays). Calls the canonical producer
(indicator_cache_refresh → indicator_engine) then drops the broker snapshot
so the next get_indicator_snapshot() rebuilds from fresh DB rows.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = PROJECT_ROOT / "state" / "data_broker" / "indicator_snapshot.json"


def invalidate_indicator_snapshot() -> bool:
    """Force next get_indicator_snapshot() to rebuild from DB."""
    try:
        if SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.unlink()
        return True
    except Exception:
        return False


def refresh_indicators(
    *,
    operator_desks: bool = False,
    main_missing_only: bool = False,
    missing_exits_only: bool = False,
    symbols: list[str] | None = None,
    limit: int = 120,
    sleep_ms: int = 400,
    max_age_hours: int = 36,
    profile: str = "swing",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Run canonical producer then invalidate broker snapshot.

    Prefer operator_desks=True for health-agent / weekend runs — covers Watch MAIN
    and Re-Entry exit gaps in one broker write.
    """
    script = PROJECT_ROOT / "scripts" / "indicator_cache_refresh.py"
    py = sys.executable
    cmd = [
        py, str(script),
        "--profile", profile,
        "--sleep-ms", str(int(sleep_ms)),
        "--max-age-hours", str(int(max_age_hours)),
    ]
    if symbols:
        cmd.extend(["--symbols", ",".join(s.upper() for s in symbols if s)])
    elif operator_desks:
        cmd.append("--operator-desks")
    elif main_missing_only:
        cmd.append("--main-missing-only")
    elif missing_exits_only:
        cmd.append("--missing-exits-only")
    else:
        cmd.append("--operator-desks")  # safe default for broker callers
    if limit and limit > 0:
        cmd.extend(["--limit", str(int(limit))])

    started = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        invalidate_indicator_snapshot()
        return {
            "ok": False,
            "error": f"timeout after {timeout_s}s",
            "started_at": started,
            "cmd": " ".join(cmd[-8:]),
            "snapshot_invalidated": True,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:240],
            "started_at": started,
            "cmd": " ".join(cmd[-8:]),
            "snapshot_invalidated": False,
        }

    invalidated = invalidate_indicator_snapshot()
    tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-800:]
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "cmd_tail": " ".join(cmd[-10:]),
        "snapshot_invalidated": invalidated,
        "producer": "scripts/indicator_cache_refresh.py → indicator_engine → indicator_confluence_cache",
        "consumers": [
            "lib.data_broker.indicator_snapshot",
            "watch_decision_desk",
            "reentry_decision_desk",
            "health_agent watch_main_indicator_cache_gap",
            "health_agent reentry_indicator_cache_gap",
        ],
        "log_tail": tail,
    }
