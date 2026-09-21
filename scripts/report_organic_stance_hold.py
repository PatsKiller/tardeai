#!/usr/bin/env python3
"""report_organic_stance_hold.py — LIVE-cio-stance-governance organic proof.

Reads ``cio_telegram_stance_holds.jsonl`` (local dual-write primary by default).

OBSERVED_LIVE (24/7, asset-agnostic, multi-workflow) requires:
  ``source=check_investment_send`` and ``caller`` in ORGANIC_HOLD_CALLERS
  (screener_go_alerts | social_scalp_scanner | send_telegram_proposal_alert).

Day-of-week is not a filter. Formerly ``PARTIAL-telegram-CIO-stance``.

USAGE
  python3 scripts/report_organic_stance_hold.py
  python3 scripts/report_organic_stance_hold.py --json
  python3 scripts/report_organic_stance_hold.py --path /path/to/holds.jsonl

Exit: 0 = organic OBSERVED; 2 = still PARTIAL (canary/probe only or empty);
      1 = error.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

NO_CONSUMER_REASON = (
    "operator / 24/7 observe timers + stdout/JSON; ledger id LIVE-cio-stance-governance "
    "(formerly PARTIAL-telegram-CIO-stance)"
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true", help="emit JSON summary")
    p.add_argument(
        "--path",
        type=Path,
        default=None,
        help="hold receipts JSONL (default: gate primary path)",
    )
    args = p.parse_args(argv)

    try:
        from scripts.lib.cio_telegram_stance_gate import (
            GAP_ID,
            summarize_stance_holds,
            write_organic_observe_receipt,
        )
    except ImportError:  # cron form: scripts on path as top-level
        from lib.cio_telegram_stance_gate import (  # type: ignore
            GAP_ID,
            summarize_stance_holds,
            write_organic_observe_receipt,
        )

    summary = summarize_stance_holds(args.path)
    summary["no_consumer_reason"] = NO_CONSUMER_REASON
    summary["observe_receipt"] = write_organic_observe_receipt(summary)

    if args.json:
        print(json.dumps(summary, sort_keys=True, indent=2))
    else:
        status = "OBSERVED" if summary.get("observed") else "PARTIAL"
        print(
            f"LIVE-cio-stance-governance: {status} "
            f"organic={summary.get('organic')} "
            f"non_organic={summary.get('non_organic')} "
            f"total={summary.get('total')} "
            f"path={summary.get('path')}"
        )
        latest = summary.get("latest_organic")
        if latest:
            print(
                f"  latest: as_of={latest.get('as_of')} "
                f"symbol={latest.get('symbol')} "
                f"caller={latest.get('caller')} "
                f"reason={latest.get('held_reason')}"
            )
        else:
            print(
                "  latest: none — awaits any-day organic GO/scalp/proposal "
                "(or other ORGANIC_HOLD_CALLERS) hold with source=check_investment_send"
            )
            print(
                "  observe windows ET (daily): early 06:35 · primary 09:05 · "
                "producers may fire any day Mon–Sun"
            )
        print(f"  gap_id={GAP_ID} scope=24/7 multi-workflow mbi_behavior=0")

    if summary.get("observed"):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
