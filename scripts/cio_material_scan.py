#!/usr/bin/env python3
"""Production CIO material scan.

Automatically loads previous/current verified holdings and current
CIO / capital / re-entry state. Manual --prev-holdings/--curr-holdings
remain as test overrides only.

Default dry_run=True. --live publishes only when CIO_ONLY_LIVE is already set.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", action="store_true", default=False)
    p.add_argument("--prev-holdings", default="", help="Test override only")
    p.add_argument("--curr-holdings", default="", help="Test override only")
    p.add_argument("--max-publish", type=int, default=3)
    args = p.parse_args(argv)
    dry = not (args.live and "--dry-run" not in (argv or sys.argv[1:]))

    from scripts.lib.cio_material_scan import scan_office
    from scripts.lib.cio_office_state import load_live_office

    office = None
    if args.prev_holdings or args.curr_holdings:
        office = load_live_office()
        if args.curr_holdings:
            office["holdings"] = json.loads(Path(args.curr_holdings).read_text())
        if args.prev_holdings:
            prev = json.loads(Path(args.prev_holdings).read_text())
            office["previous_snapshot"] = {"holdings": prev if isinstance(prev, list) else (prev.get("holdings") or [])}
            office["baseline_needed"] = False
        else:
            office["previous_snapshot"] = None
            office["baseline_needed"] = True

    receipt = scan_office(dry_run=dry, office=office, max_publish=max(1, int(args.max_publish)))
    print(json.dumps({
        "ok": receipt.get("ok"),
        "dry_run": receipt.get("dry_run"),
        "delivery_mode": receipt.get("delivery_mode"),
        "baseline_captured": receipt.get("baseline_captured"),
        "holdings_event_count": len(receipt.get("holdings_events") or []),
        "published": receipt.get("published"),
        "cash_posture_status": (receipt.get("cash") or {}).get("cash_posture_status"),
        "reentry_call": (receipt.get("reentry") or {}).get("call"),
        "due_defers": receipt.get("due_defers"),
        "results": [
            {
                "decision_id": ((r.get("evaluate") or {}).get("decision_id")
                                or (r.get("delivery") or {}).get("decision_id")),
                "published": r.get("published"),
                "event_type": r.get("event_type"),
                "case_id": r.get("case_id"),
                "delivered": (r.get("delivery") or {}).get("delivered"),
                "reason": (r.get("delivery") or {}).get("reason") or r.get("reason"),
            }
            for r in (receipt.get("results") or [])
        ],
        "receipt_path": receipt.get("receipt_path"),
        "authority": receipt.get("authority"),
    }, indent=2, default=str))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
