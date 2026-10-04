#!/usr/bin/env python3
"""Counterfactual ledger for blocked ideas (CounterfactualLedger@v1).

    python scripts/build_counterfactual_ledger.py               # dry run: per-gate summary, writes nothing
    python scripts/build_counterfactual_ledger.py --apply       # append changed measurements to the store
    python scripts/build_counterfactual_ledger.py --days 30 --json

Deterministic, read-only against the DB, no LLM. Observation only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import counterfactual_ledger as cl  # noqa: E402


def _db_query():
    import api_v2  # noqa: PLC0415
    return api_v2._db_query


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--apply", action="store_true", help="append to the ledger store (default: dry run)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = cl.build(_db_query(), days=args.days)
    written = cl.append_rows(out["rows"]) if args.apply else 0
    report = {k: v for k, v in out.items() if k != "rows"}
    report.update({"applied": bool(args.apply), "written": written})
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {out['blocks']} blocked ideas over {args.days}d "
          f"({out['rechecks_collapsed']} re-checks collapsed); written={written}")
    for g in out["summary"]:
        print(f"  {g['gate'][:48]:48} h={g['horizon_sessions']:>2} blocks={g['blocks']:>4} measured={g['measured']:>4} "
              f"pending={g['pending']:>4} stale={g['stale_identical']:>3} mean={g['mean_return_pct']} "
              f"median={g['median_return_pct']} up>5%={g['cost_good_moves_blocked']} down>5%={g['benefit_losers_avoided']}")
    print("  -- per strategy, each idea once (gate rows above can repeat an idea) --")
    for g in out.get("idea_summary") or []:
        print(f"  {g['strategy'][:32]:32} h={g['horizon_sessions']:>2} ideas={g['ideas']:>4} measured={g['measured']:>4} "
              f"mean={g['mean_return_pct']} median={g['median_return_pct']} "
              f"up>5%={g['good_moves_blocked']} down>5%={g['losers_avoided']} multi_gate={g['multi_gate_ideas']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
