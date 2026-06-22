#!/usr/bin/env python3
"""schwab_pilot_arm.py — Stage 2b pilot ARM / DISARM / STATUS (operator-run, typed-phrase confirmed).

Arms the three STANDING locks the execution guard requires (env flag is the operator's manual step):
  1. system_controls['broker_live_enabled'] = 'true'
  2. broker_live_approvals — a standing signed approval row (revocable)
  3. broker_accounts.api_write_enabled = true for every account in PILOT_ACCOUNT_ALLOWLIST (all 3 Schwab)

It can NEVER widen the per-order locks: the canary envelope (brokers/canary_gate.py) and pilot caps
(brokers/pilot_caps.py) are commit-only literals, and per-trade 2FA always applies. Disarm reverses
everything. The .env flag (BROKER_LIVE_ENABLED=true) + server restart remain manual on purpose —
arming requires touching two different surfaces.

  python3 scripts/schwab_pilot_arm.py --status
  python3 scripts/schwab_pilot_arm.py --arm    --confirm "ARM SCHWAB PILOT <YYYY-MM-DD>"
  python3 scripts/schwab_pilot_arm.py --disarm --confirm "DISARM SCHWAB PILOT"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from brokers.pilot_caps import PILOT_ACCOUNT_ALLOWLIST, MAX_PILOT_ORDERS_TOTAL, orders_used


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS system_controls (
                     key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT NOW())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS broker_live_approvals (
                     id SERIAL PRIMARY KEY, approved_by TEXT NOT NULL, note TEXT,
                     created_at TIMESTAMPTZ DEFAULT NOW(), revoked_at TIMESTAMPTZ)""")


def status() -> dict:
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur); conn.commit()
    cur.execute("SELECT value FROM system_controls WHERE key='broker_live_enabled'")
    r = cur.fetchone()
    control = bool(r and str(r[0]).lower() == "true")
    cur.execute("SELECT count(*) FROM broker_live_approvals WHERE revoked_at IS NULL")
    approvals = int(cur.fetchone()[0] or 0)
    # UI-armed session (auto-expiring 'physical key' replacing the shell env flag)
    cur.execute("SELECT value FROM system_controls WHERE key='pilot_armed_until'")
    sr = cur.fetchone()
    session_until = sr[0] if sr and sr[0] else None
    session_active = False
    if session_until:
        try:
            session_active = dt.datetime.fromisoformat(str(session_until)) > dt.datetime.now(dt.timezone.utc)
        except Exception:
            session_active = False
    cur.execute("SELECT account_key, api_write_enabled FROM broker_accounts WHERE broker ILIKE '%schwab%' ORDER BY account_key")
    accounts = {k: bool(v) for k, v in cur.fetchall()}
    from brokers import canary_gate as cg
    env_flag = os.getenv("BROKER_LIVE_ENABLED", "false").lower() == "true"
    today = dt.date.today().isoformat()
    cur.execute("SELECT value FROM system_controls WHERE key='schwab_pilot_standing_unlock'")
    sr2 = cur.fetchone()
    standing_unlock = bool(sr2 and str(sr2[0]).lower() == "true")
    key_present = env_flag or session_active or standing_unlock
    all_writes = all(accounts.get(k) is True for k in PILOT_ACCOUNT_ALLOWLIST)
    return {
        "env_BROKER_LIVE_ENABLED": env_flag,
        "pilot_armed_until": session_until,
        "pilot_session_active": session_active,
        "arm_phrase": f"ARM SCHWAB PILOT {today}",   # exact typed phrase the UI requires to arm
        "disarm_phrase": "DISARM SCHWAB PILOT",
        "db_control_broker_live_enabled": control,
        "standing_approvals_active": approvals,
        "api_write_enabled": accounts,
        "pilot_account_allowlist": list(PILOT_ACCOUNT_ALLOWLIST),
        "pilot_orders_used": orders_used(),
        "pilot_orders_cap": MAX_PILOT_ORDERS_TOTAL,
        "canary_session_date": cg.CANARY_SESSION_DATE,
        "canary_session_is_today": cg.CANARY_SESSION_DATE == today,
        "canary_allowlist": list(cg.CANARY_SYMBOL_ALLOWLIST),
        "canary_envelope": {"max_price": cg.MAX_PRICE_USD, "max_qty": cg.MAX_QTY_SHARES,
                            "max_notional": cg.MAX_NOTIONAL_USD},
        "schwab_pilot_standing_unlock": standing_unlock,
        "armed": key_present and control and approvals > 0 and all_writes,
        "note": "armed=true still places NOTHING by itself: per-order 2FA gates every submit. "
                "Standing unlock (no expiry) OR env BROKER_LIVE_ENABLED OR session key required.",
    }


def arm(confirm: str) -> dict:
    today = dt.date.today().isoformat()
    want = f"ARM SCHWAB PILOT {today}"
    if confirm != want:
        return {"ok": False, "error": f"typed confirmation mismatch — must be exactly: {want!r}"}
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('broker_live_enabled','true')
                   ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW()""")
    cur.execute("""INSERT INTO broker_live_approvals (broker, approved_by, scope)
                   VALUES ('schwab', 'operator', %s)""",
                (f"stage2b_pilot {today} (typed-phrase confirmed)",))
    for acct in PILOT_ACCOUNT_ALLOWLIST:
        cur.execute("UPDATE broker_accounts SET api_write_enabled=true WHERE account_key=%s", (acct,))
    # Standing unlock (operator 2026-06-22): no session expiry — survives restarts until disarm.
    standing_until = dt.datetime(2099, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('schwab_pilot_standing_unlock','true')
                   ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW()""")
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('pilot_armed_until', %s)
                   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
                (standing_until.isoformat(),))
    conn.commit()
    return {"ok": True, "armed_db": True, "standing_unlock": True, "armed_until": standing_until.isoformat(),
            "pilot_accounts": list(PILOT_ACCOUNT_ALLOWLIST),
            "note": "ARMED — all 3 Schwab accounts, standing unlock (no expiry). Per-order 2FA still required.",
            "status": status()}


def disarm(confirm: str) -> dict:
    if confirm != "DISARM SCHWAB PILOT":
        return {"ok": False, "error": "typed confirmation mismatch — must be exactly: 'DISARM SCHWAB PILOT'"}
    conn = _conn(); cur = conn.cursor()
    _ensure_tables(cur)
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('broker_live_enabled','false')
                   ON CONFLICT (key) DO UPDATE SET value='false', updated_at=NOW()""")
    # expire the armed session immediately (the auto-expiring 'physical key')
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('pilot_armed_until','')
                   ON CONFLICT (key) DO UPDATE SET value='', updated_at=NOW()""")
    cur.execute("""INSERT INTO system_controls (key, value) VALUES ('schwab_pilot_standing_unlock','')
                   ON CONFLICT (key) DO UPDATE SET value='', updated_at=NOW()""")
    cur.execute("UPDATE broker_live_approvals SET revoked_at=NOW() WHERE revoked_at IS NULL")
    cur.execute("UPDATE broker_accounts SET api_write_enabled=false WHERE broker ILIKE '%schwab%'")
    conn.commit()
    return {"ok": True, "disarmed_db": True, "note": "DISARMED — session expired, all locks cleared.",
            "status": status()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--arm", action="store_true")
    g.add_argument("--disarm", action="store_true")
    ap.add_argument("--confirm", default="")
    a = ap.parse_args()
    out = status() if a.status else arm(a.confirm) if a.arm else disarm(a.confirm)
    print(json.dumps(out, indent=2, default=str))
