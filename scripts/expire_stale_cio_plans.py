#!/usr/bin/env python3
"""Expire stale draft/proposed CIO plans (append-only). Dry run by default.

    python scripts/expire_stale_cio_plans.py                 # dry run: counts + sample
    python scripts/expire_stale_cio_plans.py --json
    python scripts/expire_stale_cio_plans.py --apply         # write expiry events + receipt
    python scripts/expire_stale_cio_plans.py --grace-days 14 --limit 50

Run from the release root: CIOPlanStore uses relative data/cio paths.
Rule and rationale: scripts/lib/cio_plan_expiry.py. Operator-approved 2026-10-03.
AUTHORITY: READ_ONLY_ADVISORY. Never deletes a plan; never touches accepted plans.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.cio_plan_expiry import DEFAULT_GRACE_DAYS, SCHEMA, expiry_candidates, expiry_reason  # noqa: E402
from scripts.lib.cio_plans import EXPIRABLE, CIOPlanStore  # noqa: E402

RECEIPTS = Path("data/cio/cio_plan_expiry_receipts.jsonl")


def _age_bucket(reason: str) -> str:
    try:
        days = int(reason.split("passed by ", 1)[1].split("d", 1)[0])
    except (IndexError, ValueError):
        return "?"
    return "14-30d" if days < 30 else "30-60d" if days < 60 else "60d+"


def run(*, apply: bool, grace_days: int, limit: int | None, store: CIOPlanStore | None = None,
        now: datetime | None = None, receipts: Path | None = None) -> dict:
    store = store or CIOPlanStore()
    now = now or datetime.now(timezone.utc)
    receipts = receipts or RECEIPTS
    # Count from the event log, not a drifted pre-offset projection (read-only).
    replayed = store.refresh_from_log()
    open_plans = [dict(p) for p in store._plans.values() if p.get("status") in EXPIRABLE]
    cands = expiry_candidates(open_plans, now=now, grace_days=grace_days)
    if limit is not None:
        cands = cands[:limit]
    result = {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": now.isoformat(),
        "grace_days": grace_days,
        "replayed_from_log": replayed,
        "applied": apply,
        "open_before": len(open_plans),
        "would_expire": len(cands),
        "by_situation": dict(Counter(str(p.get("situation_type")) for p, _ in cands).most_common()),
        "by_status": dict(Counter(str(p.get("status")) for p, _ in cands).most_common()),
        "by_overdue": dict(Counter(_age_bucket(r) for _, r in cands).most_common()),
        "sample": [{"plan_id": p.get("plan_id"), "situation_type": p.get("situation_type"),
                    "symbols": p.get("symbols"), "reason": r} for p, r in cands[:5]],
    }
    if apply and cands:
        expired = store.expire_plans(
            [(str(p["plan_id"]), r) for p, r in cands],
            recheck=lambda plan: expiry_reason(plan, now=now, grace_days=grace_days),
        )
        result["expired"] = len(expired)
        result["open_after"] = sum(1 for p in store._plans.values() if p.get("status") in EXPIRABLE)
        receipts.parent.mkdir(parents=True, exist_ok=True)
        with receipts.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**result, "expired_plan_ids": expired}, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Expire stale draft/proposed CIO plans (append-only)")
    ap.add_argument("--apply", action="store_true", help="write expiry events (default: dry run)")
    ap.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = run(apply=args.apply, grace_days=args.grace_days, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        mode = "APPLIED" if args.apply else "DRY RUN"
        print(f"{mode}: {result['would_expire']} of {result['open_before']} open plans "
              f"(grace {args.grace_days}d)")
        for key in ("by_situation", "by_status", "by_overdue"):
            print(f"  {key}: {result[key]}")
        for s in result["sample"]:
            print(f"  e.g. {s['plan_id']} {s['situation_type']} {s['symbols']}: {s['reason']}")
        if args.apply:
            print(f"  expired={result.get('expired', 0)} open_after={result.get('open_after')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
