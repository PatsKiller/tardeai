#!/usr/bin/env python3
"""deploy_recompute.py — refresh redeploy plans (Hermes + regime + sentiment factors).

  python3 scripts/deploy_recompute.py --apply              # all open events
  python3 scripts/deploy_recompute.py --apply --symbol FCNTX
  python3 scripts/deploy_recompute.py --apply --id 144
"""
from __future__ import annotations

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