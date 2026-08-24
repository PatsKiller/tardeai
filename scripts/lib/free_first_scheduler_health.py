"""Read-only health for the FREE_FIRST_ONLY systemd timer.

A successful FRESH_NO_CHANGE / NO_NEW_INFO run is healthy. Timer freshness
does not mean an LLM call is required.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
RECEIPT = "data/cio/free_first_last_run.json"
TIMER = "tradeai-free-first-circulation.timer"
SERVICE = "tradeai-free-first-circulation.service"


def load_receipt(root: Path | str) -> dict[str, Any] | None:
    path = Path(root) / RECEIPT
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def timer_health(root: Path | str, *, timer_show: dict[str, str] | None = None) -> dict[str, Any]:
    rec = load_receipt(root) or {}
    paid = int(rec.get("paid_dispatch_entered") or rec.get("paid_calls_attempted") or 0)
    last_ok = bool(rec) and paid == 0 and rec.get("overlap") is not True
    return {
        "schema": "FreeFirstSchedulerHealth@v1",
        "authority": AUTHORITY,
        "timer": TIMER,
        "service": SERVICE,
        "timer_show": timer_show or {},
        "last_run_mode": rec.get("mode"),
        "last_source_sha": rec.get("source_sha"),
        "last_run_id": rec.get("run_id"),
        "last_finished_at": rec.get("finished_at") or rec.get("as_of"),
        "paid_dispatch_count": paid,
        "fresh_no_change": rec.get("fresh_no_change"),
        "healthy": last_ok,
        "note": "NO_NEW_INFO / FRESH_NO_CHANGE is a healthy outcome",
        "financial_action": False,
    }
