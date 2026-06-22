#!/usr/bin/env python3
"""options_pilot_arm.py — operator approval for Schwab options execution (typed-phrase confirmed).

Sets system_controls['options_execution_enabled']='true'. Does NOT flip ENABLED in
options_execution_policy.py (commit-only) — operator must also commit ENABLED=True there.

Usage:
  python3 scripts/options_pilot_arm.py --status
  python3 scripts/options_pilot_arm.py --approve --confirm "APPROVE OPTIONS EXECUTION YYYY-MM-DD"
  python3 scripts/options_pilot_arm.py --revoke --confirm "REVOKE OPTIONS EXECUTION"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS system_controls (
                     key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT NOW())""")


def status() -> dict:
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("SELECT value FROM system_controls WHERE key='options_execution_enabled'")
    r = cur.fetchone()
    enabled_db = bool(r and str(r[0]).lower() == "true")
    try:
        from brokers import options_execution_policy as oep
        policy_enabled = oep.ENABLED
    except Exception:
        policy_enabled = False
    today = dt.date.today().isoformat()
    return {
        "options_execution_enabled": enabled_db,
        "policy_ENABLED_commit": policy_enabled,
        "armed_for_execution": enabled_db and policy_enabled,
        "approve_phrase": f"APPROVE OPTIONS EXECUTION {today}",
        "revoke_phrase": "REVOKE OPTIONS EXECUTION",
        "note": "Both DB approve AND options_execution_policy.ENABLED=True commit required for live submit.",
    }


def approve(confirm: str) -> dict:
    today = dt.date.today().isoformat()
    want = f"APPROVE OPTIONS EXECUTION {today}"
    if confirm != want:
        return {"ok": False, "error": f"must be exactly: {want!r}"}
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('options_execution_enabled','true')
                   ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW()""")
    conn.commit()
    return {"ok": True, "options_execution_enabled": True, "status": status()}


def revoke(confirm: str) -> dict:
    if confirm != "REVOKE OPTIONS EXECUTION":
        return {"ok": False, "error": 'must be exactly: "REVOKE OPTIONS EXECUTION"'}
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('options_execution_enabled','')
                   ON CONFLICT (key) DO UPDATE SET value='', updated_at=NOW()""")
    conn.commit()
    return {"ok": True, "options_execution_enabled": False, "status": status()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--revoke", action="store_true")
    ap.add_argument("--confirm", default="")
    a = ap.parse_args()
    if a.approve:
        print(json.dumps(approve(a.confirm), indent=2, default=str))
    elif a.revoke:
        print(json.dumps(revoke(a.confirm), indent=2, default=str))
    else:
        print(json.dumps(status(), indent=2, default=str))


if __name__ == "__main__":
    main()