#!/usr/bin/env python3
"""Expire stale empty draft plans (dry-run default).

  PYTHONPATH=.:scripts python3 scripts/cio_draft_plan_hygiene.py
  PYTHONPATH=.:scripts python3 scripts/cio_draft_plan_hygiene.py --apply --limit 50

Does not delete jsonl history. No notify.
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
    ap.add_argument("--apply", action="store_true", help="Write PLAN_UPDATED/STATUS_CHANGED (default dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max plans (0 = all eligible)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--expire-stale", action="store_true",
                    help="also expire draft/proposed plans past revisit_at + grace (expire_stale_cio_plans)")
    ap.add_argument("--grace-days", type=int, default=14)
    args = ap.parse_args(argv)
    from scripts.lib.cio_plans import CIOPlanStore
    from scripts.lib.cio_draft_plan_hygiene import expire_stale_empty_drafts
    store = CIOPlanStore()
    rec = expire_stale_empty_drafts(store, apply=args.apply, limit=args.limit)
    if args.json:
        print(json.dumps(rec, indent=2, default=str))
    else:
        print(f"would_expire={rec['would_expire']} expired={rec['expired']} apply={rec['apply']}")
        for s in rec.get("samples") or []:
            print(f"  {s.get('plan_id')} {s.get('situation_type')} {s.get('symbols')} revisit={s.get('revisit_at')}")
    if args.expire_stale:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "expire_stale_cio_plans", Path(__file__).resolve().parent / "expire_stale_cio_plans.py")
        sweeper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sweeper)
        swept = sweeper.run(apply=args.apply, grace_days=args.grace_days, limit=None, store=store)
        if args.json:
            print(json.dumps(swept, indent=2, default=str))
        else:
            print(f"stale_expiry would_expire={swept['would_expire']} expired={swept.get('expired', 0)} "
                  f"apply={args.apply} by_situation={swept['by_situation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
