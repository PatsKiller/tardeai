#!/usr/bin/env python3
"""Enqueue Hermes when SecurityResearchSpine tip is past CLASS_SLA.

Default --dry-run. Use --apply to call enqueue_research_gap (rate-limited).
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "ops CLI; operator/cron invokes; Hermes research queue is the consumer"
)

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--apply", action="store_true", help="actually enqueue (default dry-run)")
    ap.add_argument("--symbols", nargs="*", default=None, help="limit to these symbols")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    from scripts.lib.cross_asset.spine_sla_enqueue import enqueue_spine_sla_breaches

    out = enqueue_spine_sla_breaches(
        list(args.symbols) if args.symbols else None,
        root=args.root,
        apply=bool(args.apply),
    )
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(
            f"spine_sla_enqueue {mode}: candidates={out.get('candidates')} "
            f"selected={out.get('selected')} symbols={out.get('symbols')}"
        )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
