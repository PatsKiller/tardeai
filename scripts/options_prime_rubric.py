#!/usr/bin/env python3
"""options_prime_rubric.py — CLI for the Alpaca-lane prime-readiness rubric (Stage 3).

Scores options_approval_queue rows across the 10-component rubric
(lib/options_pipeline/prime_rubric.py) and persists the resulting prime_json
into the row's meta (one UPDATE). ADVISORY ONLY: the verdict is a label — this
CLI never transitions queue status and never touches an order path.

Usage:
    # score one proposal (persists meta.prime_json)
    .venv/bin/python scripts/options_prime_rubric.py --proposal-id <PROPOSAL_ID>

    # score every queued/in-lane row
    .venv/bin/python scripts/options_prime_rubric.py --all-queued

    # machine-readable output / score without persisting
    .venv/bin/python scripts/options_prime_rubric.py --proposal-id <ID> --json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass


def _print_human(res: dict) -> None:
    if not res.get("ok"):
        print(f"ERROR: {res.get('error')}")
        return
    pj = res["prime_json"]
    print(f"{pj['proposal_id']}")
    print(f"  prime_score {pj['prime_score']:.1f} → {pj['verdict']} (label only)")
    for name, c in pj["components"].items():
        score = "excluded" if c["score"] is None else f"{c['score']:6.1f}"
        print(f"  {name:<26} {score}  w={c['weight']:.2f}  {c['detail']}")
    if pj.get("notes"):
        for n in pj["notes"]:
            print(f"  note: {n}")
    print(f"  persisted: {res.get('persisted')}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prime-readiness rubric for Alpaca paper options proposals "
                    "(advisory label only — never transitions status, never orders)")
    parser.add_argument("--proposal-id", default="", help="score one queue row")
    parser.add_argument("--all-queued", action="store_true",
                        help="score every pending/approved/Alpaca-lane row")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--dry-run", action="store_true",
                        help="score only — do NOT persist meta.prime_json")
    args = parser.parse_args(argv)

    if bool(args.proposal_id) == bool(args.all_queued):
        parser.print_help()
        print("\nREFUSED: pick exactly one of --proposal-id / --all-queued")
        return 2

    _load_env()
    from lib.options_pipeline import prime_rubric as pr

    if args.proposal_id:
        results = [pr.score_and_persist(args.proposal_id, dry_run=args.dry_run)]
    else:
        rows = pr.list_scoreable_rows()
        if not rows:
            print(json.dumps({"ok": True, "scored": 0,
                              "note": "no scoreable queue rows"}) if args.json
                  else "no scoreable queue rows")
            return 0
        results = [pr.score_and_persist(r["proposal_id"], dry_run=args.dry_run)
                   for r in rows]

    if args.json:
        print(json.dumps({"ok": all(r.get("ok") for r in results),
                          "scored": len(results), "results": results},
                         indent=2, default=str))
    else:
        for r in results:
            _print_human(r)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
