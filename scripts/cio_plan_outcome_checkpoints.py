#!/usr/bin/env python3
"""Bind OutcomeCheckpoint@v1 for held researched plans (dry-run default).

  PYTHONPATH=.:scripts python3 scripts/cio_plan_outcome_checkpoints.py
  PYTHONPATH=.:scripts python3 scripts/cio_plan_outcome_checkpoints.py --apply --limit 20

Skip CASH sleeve / Pathward CASH ticker. No invented PnL. No notify.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from scripts.lib.cio_plan_outcome_checkpoints import bind_held_researched_plan_checkpoints
    rec = bind_held_researched_plan_checkpoints(apply=args.apply, limit=args.limit)
    if args.json:
        print(json.dumps(rec, indent=2, default=str))
    else:
        print(
            f"eligible={rec['eligible_n']} wrote={rec['wrote_n']} "
            f"apply={rec['apply']} skipped={rec['skipped_reasons']}"
        )
        for s in rec.get("samples") or []:
            print(f"  {s.get('plan_id')} {s.get('symbol')} {s.get('situation_type')} {s.get('hermes_result_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
