#!/usr/bin/env python3
"""alert-critical-drain — the retry and inspection owner for the CRITICAL immediate delivery queue (LQ-20261107-1815).

PROCESS   operator/manual, or a lane once one is reviewed. Dry run by default; ``--apply`` is the only sending path.
CONTRACT  every CRITICAL IMMEDIATE occurrence reaches the operator through Telegram, and the delivery row says who
          claimed it, when, and which Telegram message id proves it.
WHY       Measured 2026-11-10 (handoffs/audit-revalidation-20261110 §C1): 676 delivery rows, 0 ever 'sent', 0 with a
          claimant, 0 with a telegram_message_id. The queue had a schema with claim semantics, a producer and a
          janitor, and no consumer. ``alert_outbox.deliver_critical`` is that consumer; this script is its dry run and
          its retry entry point (the primary call site is the alert producer itself, so a new critical alert needs no
          schedule to be delivered).
DRY RUN   read-only: lists exactly the rows ``--apply`` would claim (occurrence, alert type, ET time, age, the reason
          the row is undelivered, the destination and whether a chat id is configured). It never prints a chat id, a
          token or a message body.
MBI_BEHAVIOR = 0: nothing here sizes, orders, stops, weights or touches a broker.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "alert-critical-drain"
ET = ZoneInfo("America/New_York")


def _et(value) -> str | None:
    if value is None:
        return None
    try:
        return value.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    except Exception:
        return str(value)


def plan(*, limit: int, min_age_s: int) -> dict:
    """The rows an apply would claim right now, plus what the operator-facing destination resolves to (presence only)."""
    import alert_outbox

    rows = alert_outbox.critical_due(limit=limit, min_age_s=min_age_s)
    destinations = {}
    for row in rows:
        dest = str(row.get("logical_destination") or "")
        if dest not in destinations:
            chat_id, _thread = alert_outbox.resolve_channel_secret(row.get("logical_destination"))
            destinations[dest] = {"chat_configured": bool(chat_id)}
    return {
        "lane_id": LANE_ID,
        "mode": "dry_run",
        "generated_at": _et(__import__("datetime").datetime.now(timezone.utc)),
        "would_claim": len(rows),
        "destinations": destinations,
        "rows": [
            {
                "delivery_row_id": r.get("id"),
                "occurrence_id": r.get("occurrence_id"),
                "alert_id": r.get("alert_id"),
                "alert_type": r.get("alert_type"),
                "severity": r.get("severity"),
                "observed_et": _et(r.get("observed_at")),
                "status": r.get("delivery_status"),
                "retry_count": r.get("retry_count"),
                "undelivered_reason": r.get("delivery_reason"),
                "destination": r.get("logical_destination"),
            }
            for r in rows
        ],
        "sends": 0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="claim and send (default: dry run, read-only)")
    ap.add_argument("--limit", type=int, default=5, help="rows per run (default 5)")
    ap.add_argument("--min-age-s", type=int, default=0,
                    help="only rows at least this old (default 0; a scheduled drain should keep the legacy path a head start)")
    args = ap.parse_args(argv)
    if not args.apply:
        print(json.dumps(plan(limit=args.limit, min_age_s=args.min_age_s), indent=1, default=str))
        return 0
    import alert_outbox

    out = alert_outbox.deliver_critical(limit=args.limit, min_age_s=args.min_age_s)
    print(json.dumps({**out, "lane_id": LANE_ID, "mode": "apply"}, indent=1, default=str))
    return 0 if out.get("ok") or not out.get("claimed") else 1


if __name__ == "__main__":
    sys.exit(main())
