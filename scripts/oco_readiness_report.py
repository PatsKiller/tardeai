#!/usr/bin/env python3
"""Read-only OCO canary readiness report.

OCO remains disabled unless all prerequisite basic protective-stop canaries and
guards are clean. This script reports blockers; it does not enable anything.
"""
from __future__ import annotations

import json
import os


def build_report() -> dict:
    oco_enabled = os.getenv("OCO_BRACKETS_SCHWAB", "").strip().lower() in {"1", "true", "yes", "on"}
    checks = {
        "oco_brackets_schwab_off": not oco_enabled,
        "db_available": False,
        "execution_state_operator_2fa_live_allowed": False,
        "protective_stop_canary_passed": False,
        "trailing_stop_canary_passed": False,
        "evidence_bound_approval_clean": False,
        "read_back_verified": False,
        "kill_switches_clear": False,
    }
    blockers: list[str] = []
    if oco_enabled:
        blockers.append("OCO_BRACKETS_SCHWAB is enabled; must remain OFF before readiness review.")
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        checks["db_available"] = cur.fetchone()[0] == 1
    except Exception as e:
        blockers.append(f"DB unavailable: {str(e)[:120]}")
    try:
        from brokers.kill_switches import is_blocked
        blocked, reasons = is_blocked(live_submit=True)
        checks["kill_switches_clear"] = not blocked
        if blocked:
            blockers.extend([f"kill switch: {r}" for r in reasons[:5]])
    except Exception as e:
        blockers.append(f"kill switch check failed: {str(e)[:120]}")

    for name in (
        "protective_stop_canary_passed",
        "trailing_stop_canary_passed",
        "evidence_bound_approval_clean",
        "read_back_verified",
    ):
        if not checks[name]:
            blockers.append(f"{name} is not proven")
    ready = all(checks.values())
    return {"ok": True, "ready_for_oco_one_share_canary": ready, "checks": checks, "blockers": blockers}


def main() -> None:
    print(json.dumps(build_report(), indent=2, default=str))


if __name__ == "__main__":
    main()
