#!/usr/bin/env python3
"""reverse_factor_backfill.py — one-shot reverse-factor `n` backfill (Phase 5 §8).

Recomputes and folds the three reliability-gate sample sizes on `watchlist_items`
from their canonical source tables so existing rows stop being damped to zero by the
scorer. Advisory-only, idempotent, dry-runnable.

  python3 scripts/reverse_factor_backfill.py                 # dry-run summary
  python3 scripts/reverse_factor_backfill.py --apply         # fold the backfill
  python3 scripts/reverse_factor_backfill.py --apply --limit 250
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.cio_reverse_factor_backfill import backfill  # noqa: E402


def _render(summary: dict) -> str:
    lines = [
        "Reverse-factor `n` backfill",
        "============================",
        f"dry_run      : {summary.get('dry_run')}",
        "",
        "thesis_outcome  (hermes_outcome_ledger / trade)",
        f"  candidates : {summary['thesis_outcome']['candidates']}",
        f"  written    : {summary['thesis_outcome']['written']}",
        "",
        "hermes_research (hermes_outcome_ledger / research_row)",
        f"  candidates : {summary['hermes_research']['candidates']}",
        f"  written    : {summary['hermes_research']['written']}",
        "",
        "options_edge    (options_paper_outcomes / approval_queue / iv_history)",
        f"  candidates : {summary['options_edge']['candidates']}",
        f"  written    : {summary['options_edge']['written']}",
        f"  skipped    : {summary['options_edge']['skipped']}",
        f"  errors     : {summary['options_edge']['errors']}",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="fold the backfill (default is dry-run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap options-edge candidate universe (default 500)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit machine-readable JSON")
    args = ap.parse_args()

    try:
        summary = backfill(dry_run=not args.apply, limit=args.limit)
    except Exception as exc:  # fail-soft: never wedge the cron on a missing table
        print(json.dumps({"ok": False, "error": str(exc)[:200]}))
        sys.exit(0)

    if args.as_json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(_render(summary))


if __name__ == "__main__":
    main()
