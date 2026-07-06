#!/usr/bin/env python3
"""fidelity_stop_sync.py — record Fidelity GTC sell stops for Stop Management (read-only).

SnapTrade syncs Fidelity positions and activities but returns zero open/pending orders — GTC stops
placed in Fidelity Active Trader must be recorded here. Dry-run by default.

  python3 scripts/fidelity_stop_sync.py                    # dry-run known rollover stops
  python3 scripts/fidelity_stop_sync.py --apply          # persist to manual_broker_stops
  python3 scripts/fidelity_stop_sync.py --apply --json stops.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.fidelity_stop_sync import (  # noqa: E402
    default_fidelity_rollover_stops,
    sync_stops,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync Fidelity GTC stops into manual_broker_stops")
    ap.add_argument("--apply", action="store_true", help="Write to DB (default: dry-run)")
    ap.add_argument("--json", help="JSON file: list of {symbol, stop_price, qty, account?, placed_date?}")
    ap.add_argument("--no-retire", action="store_true", help="Do not deactivate stops absent from input")
    args = ap.parse_args()

    if args.json:
        rows = json.loads(Path(args.json).read_text())
        if isinstance(rows, dict):
            rows = rows.get("stops") or rows.get("rows") or []
    else:
        rows = default_fidelity_rollover_stops()

    report = sync_stops(rows, retire_absent=not args.no_retire, apply=args.apply)
    print(json.dumps(report, indent=2, default=str))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())