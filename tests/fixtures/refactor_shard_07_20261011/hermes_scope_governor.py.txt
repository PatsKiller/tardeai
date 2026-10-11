#!/usr/bin/env python3
"""hermes_scope_governor.py — Hermes Scope Governor Agent (sole owner of scope_tier).

Dynamically manages what Hermes monitors via Hot/Warm/Cold tiers (S0+S1 / S2 / S3).
Outcome yield outranks throughput yield. Advisory-only — never touches orders or 2FA.

  python3 scripts/hermes_scope_governor.py --dry-run
  python3 scripts/hermes_scope_governor.py --apply
  python3 scripts/hermes_scope_governor.py --inspect
  python3 scripts/hermes_scope_governor.py --inspect --symbol AAPL

See docs/hermes/HERMES_SCOPE_GOVERNOR.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"


def _inspect(symbol: str | None = None) -> dict:
    from lib.hermes_scope_governor.universe import read_universe_feed
    from db_adapter import _get_conn, USE_DB

    feed = read_universe_feed() or {}
    out = {
        "ok": True,
        "mode": "inspect",
        "feed": feed,
        "recent_audit": [],
    }
    if USE_DB:
        conn = _get_conn()
        cur = conn.cursor()
        if symbol:
            cur.execute("""SELECT run_id, symbol, action, from_tier, to_tier, reason, created_at
                           FROM scope_governor_audit WHERE UPPER(symbol)=UPPER(%s)
                           ORDER BY created_at DESC LIMIT 20""", (symbol.upper(),))
        else:
            cur.execute("""SELECT run_id, symbol, action, from_tier, to_tier, reason, created_at
                           FROM scope_governor_audit ORDER BY created_at DESC LIMIT 30""")
        cols = [d[0] for d in cur.description] if cur.description else []
        out["recent_audit"] = [dict(zip(cols, row)) for row in cur.fetchall()]
        for row in out["recent_audit"]:
            if row.get("created_at"):
                row["created_at"] = str(row["created_at"])
    if symbol and feed.get("symbols"):
        out["symbol"] = next((s for s in feed["symbols"] if s.get("symbol") == symbol.upper()), None)
    return out


def run(apply: bool = False, reaction_review: bool = False) -> dict:
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — governor idle"}
        try:
            from lib.hermes_scope_governor.heartbeat import GOVERNOR_HEARTBEAT, write_heartbeat
            write_heartbeat(GOVERNOR_HEARTBEAT, out)
        except Exception:
            pass
        print(json.dumps(out))
        return out

    from db_adapter import _get_conn
    from lib.hermes_scope_governor.engine import ScopeGovernorEngine

    engine = ScopeGovernorEngine(PROJECT_ROOT)
    conn = _get_conn()
    out = engine.run(conn, apply=apply, reaction_review=reaction_review)
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser(description="Hermes Scope Governor Agent")
    ap.add_argument("--apply", action="store_true", help="Apply tier changes to DB")
    ap.add_argument("--dry-run", action="store_true", help="Compute decisions without writes (default)")
    ap.add_argument("--inspect", action="store_true", help="Show governed universe feed + recent audit")
    ap.add_argument("--symbol", type=str, default=None, help="Filter inspect to one symbol")
    ap.add_argument("--reaction-review", action="store_true",
                    help="Log bus reactions without applying edge/cap/runtime overrides")
    ap.add_argument("--json", action="store_true", help="JSON output (default; scripting parity)")
    args = ap.parse_args()

    if args.inspect:
        print(json.dumps(_inspect(args.symbol), indent=2, default=str))
        return

    run(apply=args.apply and not args.dry_run, reaction_review=args.reaction_review)


if __name__ == "__main__":
    main()