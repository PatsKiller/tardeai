#!/usr/bin/env python3
"""Admit WATCH InstrumentRecord rows from the operator watchlist.

Cognition only (apply_cognition, notify_priority=none). Cap 20.
Dry-run by default. No S7 fire. No Maria workers. No Telegram.

  cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
  python3 scripts/cio_admit_watch_instrument_records.py [--apply]

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Persist admitted WATCH records (default: dry-run)")
    ap.add_argument("--cap", type=int, default=None,
                    help="Max admits this run (default 20)")
    ap.add_argument("--root", default=None,
                    help="served tree (default $TRADEAI_ROOT or cwd)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    data_root = args.root or os.environ.get("TRADEAI_ROOT") or "."
    from scripts.lib.cio_watch_instrument_admit import ADMIT_CAP, admit_watch_records

    cap = int(args.cap) if args.cap is not None else ADMIT_CAP
    receipt = admit_watch_records(
        root=Path(data_root), cap=cap, apply=bool(args.apply))
    if args.json:
        print(json.dumps(receipt, indent=2, default=str))
    else:
        print(
            f"admitted_n={receipt['admitted_n']} cap={receipt['cap']} "
            f"candidates={receipt['candidates']} apply={receipt['apply']} "
            f"s7_fired={receipt['s7_fired']} maria={receipt['maria_invoked']} "
            f"keys={receipt['admitted']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
