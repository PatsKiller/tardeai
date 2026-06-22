#!/usr/bin/env python3
"""snaptrade_pilot_arm.py — operator approval for Fidelity monitored stops (typed-phrase confirmed).

Does NOT flip BROKER_API_ENABLED (commit-only) — Fidelity remains read-only on SnapTrade.
Sets standing DB unlock: system_controls['fidelity_stops_enabled']='true'.

Usage:
  python3 scripts/snaptrade_pilot_arm.py --status
  python3 scripts/snaptrade_pilot_arm.py --capability
  python3 scripts/snaptrade_pilot_arm.py --approve --confirm "APPROVE FIDELITY STOPS YYYY-MM-DD"
  python3 scripts/snaptrade_pilot_arm.py --revoke --confirm "REVOKE FIDELITY STOPS"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS system_controls (
                     key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT NOW())""")


def capability() -> dict:
    try:
        sys.path.insert(0, os.path.join(HERE, "brokers"))
        from brokers import snaptrade_trade as st
        from brokers.snaptrade_protective_stop_policy import BROKER_API_ENABLED, MONITORED_ENABLED
        ok, detail = st.broker_allows_trading()
        return {
            "snaptrade_trade_ENABLED": st.ENABLED,
            "BROKER_API_ENABLED": BROKER_API_ENABLED,
            "MONITORED_ENABLED": MONITORED_ENABLED,
            "broker_allows_trading": ok,
            "broker_detail": detail,
            "snaptrade_order_types": list(st.ALLOWED_ORDER_TYPES),
            "trailing_via_snaptrade_api": False,
            "fidelity_read_only": not ok,
            "production_path": "monitored (software stop + 2FA + Fidelity Active Trader ticket on breach)",
            "note": "SnapTrade equity API supports Stop/StopLimit only — no native trailing. "
                    "Trailing for Fidelity uses monitored ratchet in fidelity_monitored_stop.py.",
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def status() -> dict:
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("SELECT value FROM system_controls WHERE key='fidelity_stops_enabled'")
    r = cur.fetchone()
    enabled = bool(r and str(r[0]).lower() == "true")
    try:
        import fidelity_monitored_stop as fms
        armed = len(fms.list_stops("armed"))
    except Exception:
        armed = -1
    cap = capability()
    today = dt.date.today().isoformat()
    return {
        "fidelity_stops_enabled": enabled,
        "approve_phrase": f"APPROVE FIDELITY STOPS {today}",
        "revoke_phrase": "REVOKE FIDELITY STOPS",
        "monitored_stops_armed": armed,
        "capability": cap,
        "armed_for_ui": enabled and cap.get("MONITORED_ENABLED"),
        "note": "armed_for_ui=true enables the LIVE monitored route on fidelity_rollover_ira Open Trades cards "
                "(2FA per order). Broker API submit stays off while Fidelity is read-only on SnapTrade.",
    }


def approve(confirm: str) -> dict:
    today = dt.date.today().isoformat()
    want = f"APPROVE FIDELITY STOPS {today}"
    if confirm != want:
        return {"ok": False, "error": f"typed confirmation mismatch — must be exactly: {want!r}"}
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('fidelity_stops_enabled','true')
                   ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW()""")
    conn.commit()
    return {"ok": True, "fidelity_stops_enabled": True, "status": status()}


def revoke(confirm: str) -> dict:
    if confirm != "REVOKE FIDELITY STOPS":
        return {"ok": False, "error": 'typed confirmation mismatch — must be exactly: "REVOKE FIDELITY STOPS"'}
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('fidelity_stops_enabled','')
                   ON CONFLICT (key) DO UPDATE SET value='', updated_at=NOW()""")
    conn.commit()
    return {"ok": True, "fidelity_stops_enabled": False, "status": status()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--capability", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--revoke", action="store_true")
    ap.add_argument("--confirm", default="")
    a = ap.parse_args()
    if a.capability:
        print(json.dumps(capability(), indent=2))
    elif a.approve:
        print(json.dumps(approve(a.confirm), indent=2, default=str))
    elif a.revoke:
        print(json.dumps(revoke(a.confirm), indent=2, default=str))
    else:
        print(json.dumps(status(), indent=2, default=str))


if __name__ == "__main__":
    main()