#!/usr/bin/env python3
"""Write settled-outcome beliefs onto InstrumentRecords (tranche 1, Slice 2).

    .venv/bin/python scripts/write_instrument_beliefs.py            # dry run
    .venv/bin/python scripts/write_instrument_beliefs.py --apply
    .venv/bin/python scripts/write_instrument_beliefs.py --apply --json

Reads settled rows only (advisory_outcomes, resolved checkpoints with a price
change, CONFIRMED/REFUTED commitment outcomes) plus ratified lessons, and
persists through cio_instrument_record.apply_belief. Output signal:
data/cio/instrument_belief_latest.json (json_key written_beliefs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.cio_belief_writer import update_beliefs_from_settled  # noqa: E402

# Lane instrument-belief-writer (config/lane_registry.json). Proposed, not
# installed — a new cron entry is operator-only (AGENTS.md §17, §9.3):
#   50 18 * * * cd $CUR && .venv/bin/python scripts/write_instrument_beliefs.py --apply
# after resolve_due_checkpoints (:20 hourly), the commitment sweep (18:20) and
# the advisory outcome scorer (18:30) have settled the day's rows.
SCHEDULED_ENTRYPOINT = "cron: 50 18 * * * -- daily, --apply (lane instrument-belief-writer; installed 2026-09-24 under an operator cron grant)"

DEFAULT_WAKE_ROOT = Path.home() / "trade-ai-state" / "persistent_wake" / "state"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write beliefs (default: dry run)")
    ap.add_argument("--root", default=None, help="state root (default: canonical production_state_root)")
    ap.add_argument("--wake-root", default=os.environ.get("TRADEAI_WAKE_STATE_ROOT") or str(DEFAULT_WAKE_ROOT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.root:
        root = Path(args.root)
    else:
        from scripts.lib.canonical_store_registry import production_state_root
        root = production_state_root()
    out = update_beliefs_from_settled(root, wake_root=args.wake_root, apply=args.apply)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        mode = "APPLIED" if args.apply else "DRY-RUN"
        print(f"[{mode}] settled={out['settled_rows']} groups={out['groups']} "
              f"written={out['written_beliefs']} would_write={out['would_write_beliefs']} "
              f"noop={out['noop']} refused={out['refused']} subjects={out['subjects_written']} "
              f"skipped={out['skipped']} store={out['store']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
