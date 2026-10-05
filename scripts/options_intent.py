#!/usr/bin/env python3
"""Operator options intents: add / list / pause / archive. Dry run by default; --apply writes.

  options_intent.py add SPCX --target 300 --goals accumulate,income \
      --csp-dte 25-45 --csp-strike-max 157.85 --csp-delta 0.15-0.35 --csp-accounts schwab_rollover_ira=1 \
      --cc-dte 20-50 --cc-min-strike 230 --cc-delta 0.03-0.20 --cc-accounts schwab_rollover_ira=3,schwab_taxable=1 \
      --leap --avoid-earnings-cross --earnings-estimate 2026-11-03 --rationale "..." [--apply]
  options_intent.py list
  options_intent.py pause SPCX [--apply]     |   options_intent.py archive SPCX [--apply]

The intent is stored on the symbol's ticker watch directive (spec.options_intent) through the one
watch_directives writer. Advisory memory only — nothing sizes or orders (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.options_intent import store  # noqa: E402


def _accounts(s):
    if not s:
        return None
    out = {}
    for part in s.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = int(v or 1)
    return out


def build_intent(a) -> dict:
    plays = {}
    if a.csp_dte or a.csp_strike_max is not None:
        plays["cash_secured_put"] = {k: v for k, v in {
            "dte": a.csp_dte or "25-45", "strike_max": a.csp_strike_max, "delta": a.csp_delta or "0.15-0.35",
            "accounts": _accounts(a.csp_accounts), "max_contracts": a.csp_max_contracts}.items() if v is not None}
    if a.cc_dte or a.cc_min_strike is not None or a.cc_keep_upside_pct is not None:
        plays["covered_call"] = {k: v for k, v in {
            "dte": a.cc_dte or "20-50", "min_strike": a.cc_min_strike, "keep_upside_pct": a.cc_keep_upside_pct,
            "delta": a.cc_delta or "0.03-0.20", "accounts": _accounts(a.cc_accounts)}.items() if v is not None}
    if a.leap:
        plays["leap_call"] = {"min_dte": a.leap_min_dte, "min_delta": a.leap_min_delta}
    return {"symbol": a.symbol, "thesis_target": a.target, "thesis_source": a.target_source,
            "goals": [g for g in (a.goals or "").split(",") if g], "plays": plays,
            "avoid_earnings_cross": a.avoid_earnings_cross, "earnings_estimate": a.earnings_estimate,
            "rationale": a.rationale or ""}


def _conn():
    from db_adapter import get_connection  # type: ignore
    return get_connection()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["add", "list", "pause", "archive", "resume"])
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", type=float)
    ap.add_argument("--target-source")
    ap.add_argument("--goals")
    ap.add_argument("--csp-dte"); ap.add_argument("--csp-strike-max", type=float); ap.add_argument("--csp-delta")
    ap.add_argument("--csp-accounts"); ap.add_argument("--csp-max-contracts", type=int)
    ap.add_argument("--cc-dte"); ap.add_argument("--cc-min-strike", type=float); ap.add_argument("--cc-delta")
    ap.add_argument("--cc-keep-upside-pct", type=float); ap.add_argument("--cc-accounts")
    ap.add_argument("--leap", action="store_true"); ap.add_argument("--leap-min-dte", type=int, default=300)
    ap.add_argument("--leap-min-delta", type=float, default=0.7)
    ap.add_argument("--avoid-earnings-cross", action="store_true")
    ap.add_argument("--earnings-estimate")
    ap.add_argument("--rationale")
    ap.add_argument("--source", default="operator")
    a = ap.parse_args(argv)
    conn = _conn()
    try:
        cur = conn.cursor()
        if a.cmd == "list":
            print(json.dumps(store.load_intents(cur, include_inactive=True), indent=2, default=str))
            return 0
        if not a.symbol:
            ap.error("symbol required")
        if a.cmd == "add":
            plan = store.upsert_intent(cur, build_intent(a), source=a.source, apply=a.apply)
        else:
            status = {"pause": "paused", "archive": "archived", "resume": "active"}[a.cmd]
            plan = store.set_intent_status(cur, a.symbol, status, source=a.source, apply=a.apply)
        if a.apply:
            conn.commit()
        else:
            conn.rollback()
            plan["note"] = "DRY RUN — nothing written; re-run with --apply"
        print(json.dumps(plan, indent=2, default=str))
        return 0
    except ValueError as e:
        conn.rollback()
        print(json.dumps({"refused": str(e)}))
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
