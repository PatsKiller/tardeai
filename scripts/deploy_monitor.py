#!/usr/bin/env python3
"""deploy_monitor.py — Phase E redeploy monitoring cron (fills, restoration, re-eval).

Run after deploy_detect / holdings sync or nightly:

  python3 scripts/deploy_monitor.py              # dry-run summary
  python3 scripts/deploy_monitor.py --apply      # persist monitor snapshots
  python3 scripts/deploy_monitor.py --apply --id 144
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

    _dr_lane = "deploy-monitor"
    _dr_would = (
        "re-evaluate open deploy_events (fills, restoration; --id / --limit) and, with --apply, persist "
        "redeploy monitor snapshots"
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

from lib.redeploy_monitor import get_monitoring_state, persist_monitor_snapshot, reeval_open_events  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Redeploy monitoring re-eval (Phase E)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--id", type=int, help="Single deploy_event id")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    if not args.apply:
        from lib.sale_event_detector import detect_sell_events
        from lib.deploy_intelligence_engine import enrich_event
        events = detect_sell_events(days=30)[:5]
        preview = [enrich_event(e) for e in events]
        print(json.dumps({"applied": False, "preview_events": len(preview)}, indent=2))
        return 0

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    if args.id:
        state = get_monitoring_state(cur, args.id)
        snap = persist_monitor_snapshot(cur, args.id)
        report = {"ok": True, "event_id": args.id, "state": state, "snapshot": snap}
    else:
        report = reeval_open_events(cur, limit=args.limit)
    conn.commit()
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())