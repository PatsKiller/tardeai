#!/usr/bin/env python3
"""Scan capital plan + holdings delta + re-entry and publish material CIO events.

Default dry_run=True. Live send only when CIO_ONLY_LIVE gates are already set
in the environment. Timer/systemd should typically run dry unless mode=live.

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
    p.add_argument("--prev-holdings", default="")
    p.add_argument("--curr-holdings", default="")
    args = p.parse_args(argv)
    dry = not (args.live and "--dry-run" not in (argv or sys.argv[1:]))

    from scripts.lib.cio_holdings_delta import diff_holdings
    from scripts.lib.cio_material_publisher import publish_material_decision
    from scripts.lib.cio_telegram_transport import cio_delivery_mode

    results = []
    mode = cio_delivery_mode()
    if args.live and mode != "CIO_ONLY_LIVE":
        dry = True

    prev = curr = None
    if args.prev_holdings and args.curr_holdings:
        prev = json.loads(Path(args.prev_holdings).read_text())
        curr = json.loads(Path(args.curr_holdings).read_text())
        for ev in diff_holdings(prev, curr):
            if ev.get("event") == "POSITION_OPENED":
                dec = {
                    "decision_id": f"dec_open_{ev['symbol']}_{ev.get('account')}",
                    "symbol": ev["symbol"],
                    "action": "RESEARCH",
                    "stance": "RESEARCH",
                    "why_now": f"Verified book shows new position {ev['symbol']} ({ev.get('account')}).",
                    "counter_thesis": "Could be a transfer — purchase not claimed without evidence.",
                    "what_changes_call": "Lot history or ACATS evidence arrives.",
                    "recommended_delta_usd": 0,
                    "decision_input_digest": ev.get("event"),
                    "decision_evidence_digest": str(ev.get("value_usd")),
                }
                results.append(publish_material_decision(dec, dry_run=dry, event_type="POSITION_OPENED"))

    print(json.dumps({
        "ok": True,
        "dry_run": dry,
        "delivery_mode": mode,
        "published": len(results),
        "results": results,
        "authority": "READ_ONLY_ADVISORY",
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
