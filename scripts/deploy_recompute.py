#!/usr/bin/env python3
"""deploy_recompute.py — refresh redeploy plans (Hermes + regime + sentiment factors).

  python3 scripts/deploy_recompute.py --apply              # all open events
  python3 scripts/deploy_recompute.py --apply --symbol FCNTX
  python3 scripts/deploy_recompute.py --apply --id 144
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (--apply). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "deploy-recompute"
    _dr_would = (
        "recompute the redeploy plan (Hermes + regime + sentiment factors) of open deploy_events (--id / "
        "--symbol / --limit) and, with --apply, commit the updated plan rows"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="deploy_event"))
    raise SystemExit(0)

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.deploy_intelligence_engine import recompute_all_open, recompute_deploy_event  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Recompute deploy redeploy plans")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--id", type=int)
    ap.add_argument("--symbol", help="Recompute open events for symbol")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    if not args.apply:
        from lib.sale_event_detector import detect_sell_events
        from lib.deploy_intelligence_engine import enrich_event
        events = detect_sell_events(days=30)
        if args.symbol:
            events = [e for e in events if str(e.get("symbol")).upper() == args.symbol.upper()]
        out = [enrich_event(e) for e in events[: args.limit]]
        print(json.dumps({"applied": False, "events": out}, indent=2, default=str))
        return 0
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    if args.id:
        report = recompute_deploy_event(cur, args.id)
    elif args.symbol:
        cur.execute(
            "SELECT id FROM deploy_events WHERE upper(symbol)=%s AND status='open' ORDER BY sold_at DESC",
            (args.symbol.upper(),),
        )
        report = {"ok": True, "results": [recompute_deploy_event(cur, r[0]) for r in cur.fetchall()]}
    else:
        report = recompute_all_open(cur, limit=args.limit)
    conn.commit()
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())