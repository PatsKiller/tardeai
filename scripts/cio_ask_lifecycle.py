#!/usr/bin/env python3
"""Native n8n Ask lifecycle: hourly checks, or material polling with --events-only.

--dry-run reports intended work without reading provider credentials, calling a
source/model, taking a writer lock or writing any business/receipt artifact.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--events-only", action="store_true")
    args = parser.parse_args(argv)
    from scripts.lib.cio_ask_lifecycle import run_once

    started = datetime.now(timezone.utc)
    run_id = os.environ.get("TRADEAI_RUN_ID")
    summary = run_once(dry_run=args.dry_run, events_only=args.events_only, run_id=run_id)
    print(json.dumps(summary, default=str, sort_keys=True))
    if args.dry_run:
        return 0 if summary.get("ok") else 1
    from scripts.lib.lane_last_receipt import write_lane_receipt

    lane_id = "cio-ask-material-events" if args.events_only else "cio-ask-lifecycle"
    outputs = [
        {"kind": "ask_ledger_check", "ref": row["thread_id"]}
        for row in summary.get("threads", [])
        if row.get("consumer_readback", {}).get("state") == "verified"
    ]
    write_lane_receipt(
        lane_id,
        ok=bool(summary.get("ok")),
        exit_code=0 if summary.get("ok") else 1,
        started_at=started,
        script="scripts/cio_ask_lifecycle.py",
        summary=summary,
        attempted_count=summary.get("tracked_threads", 0),
        produced_count=summary.get("checked_count", 0),
        output_evidence=outputs,
        empty_reason=None
        if outputs
        else (
            "no_tracked_threads"
            if not summary.get("tracked_threads")
            else "no_new_events"
            if args.events_only
            else "no_due_threads"
        ),
        error="; ".join(summary.get("source_errors", []))[:400] or None,
    )
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
