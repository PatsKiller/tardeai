#!/usr/bin/env python3
"""Expire stale empty draft plans (dry-run default).

  PYTHONPATH=.:scripts python3 scripts/cio_draft_plan_hygiene.py
  PYTHONPATH=.:scripts python3 scripts/cio_draft_plan_hygiene.py --apply --limit 50

Does not delete jsonl history. No notify.

Lane cio-draft-plan-hygiene (cron L908: ``--apply``, cwd and TRADEAI_ROOT = the served release; the
plan store paths are relative to the cwd).

--dry-run wins over --apply: ``apply`` is computed once as ``args.apply and not args.dry_run`` and is
the only value handed to expire_stale_empty_drafts / the optional stale sweeper, so update_plan and the
expiry receipt append are unreachable. CIOPlanStore() itself REBUILDS AND WRITES the projection (and
creates its lock file) when the projection is missing or unreadable, so a dry run checks that first
and refuses (exit 1) instead of constructing the store. A dry run (also: no --apply) prints one
DRY-RUN report line and never writes the lane receipt.

A real (--apply) run writes <state_root>/data/runtime/cio-draft-plan-hygiene_last.json
(LaneRunReceipt@v1: would_expire / expired; ok_at only on success). Exit codes: 0 = ran (nothing
eligible is 0); 1 = the run failed: a crash (receipt ``failed``, error re-raised), or plans were
eligible and not one was expired; 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


LANE_ID = "cio-draft-plan-hygiene"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.cio_draft_plan_hygiene
        from scripts.lib import lane_last_receipt as lr
    return lr


def store_preflight(store_cls) -> str | None:
    """Dry run only: None when CIOPlanStore() can load without writing, else why it would write.

    The real store rebuilds and rewrites its projection when the projection is missing or
    unreadable; an injected factory (tests) is used as given.
    """
    if not isinstance(store_cls, type):
        return None
    from scripts.lib import cio_plans

    proj = Path(cio_plans.DEFAULT_PROJECTION_PATH)
    try:
        data = json.loads(proj.read_text())
        if isinstance(data, dict) and isinstance(data.get("plans") or {}, dict):
            return None
    except Exception:
        pass
    return f"projection {proj.resolve()} missing or unreadable: CIOPlanStore() would rebuild and write it"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write PLAN_UPDATED/STATUS_CHANGED (default dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max plans (0 = all eligible)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--expire-stale", action="store_true",
                    help="also expire draft/proposed plans past revisit_at + grace (expire_stale_cio_plans)")
    ap.add_argument("--grace-days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true", help="report only; wins over --apply")
    args = ap.parse_args(argv)
    apply = bool(args.apply and not args.dry_run)  # AGENTS.md §6: the only value passed to any writer
    from datetime import datetime, timezone
    from scripts.lib.cio_plans import CIOPlanStore
    from scripts.lib.cio_draft_plan_hygiene import expire_stale_empty_drafts
    started = datetime.now(timezone.utc).isoformat()
    summary: dict = {}
    if not apply:
        why = store_preflight(CIOPlanStore)
        if why:
            print(f"DRY-RUN refused: {why}", file=sys.stderr)
            _receipt_lib().dry_run_report(LANE_ID, {"error": "store_unreadable", "detail": why, "exit_would_be": 1})
            return 1
    try:
        store = CIOPlanStore()
        rec = expire_stale_empty_drafts(store, apply=apply, limit=args.limit)
        summary.update(would_expire=rec["would_expire"], expired=rec["expired"])
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
            swept = sweeper.run(apply=apply, grace_days=args.grace_days, limit=None, store=store)
            summary.update(stale_would_expire=swept["would_expire"], stale_expired=swept.get("expired", 0))
            if args.json:
                print(json.dumps(swept, indent=2, default=str))
            else:
                print(f"stale_expiry would_expire={swept['would_expire']} expired={swept.get('expired', 0)} "
                      f"apply={apply} by_situation={swept['by_situation']}")
    except Exception as exc:
        if apply:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="cio_draft_plan_hygiene.py", summary=summary,
                                              error=f"{type(exc).__name__}: {exc}")
        raise
    if not apply:
        _receipt_lib().dry_run_report(LANE_ID, summary, would_write=[
            "data/cio/cio_plans.jsonl PLAN_UPDATED/STATUS_CHANGED -> cancelled x would_expire"]
            + (["data/cio/cio_plan_expiry_receipts.jsonl (append)"] if args.expire_stale else []))
        return 0
    failed = (summary["would_expire"] > 0 and summary["expired"] == 0) or (
        summary.get("stale_would_expire", 0) > 0 and summary.get("stale_expired", 0) == 0)
    rc = 1 if failed else 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                                      script="cio_draft_plan_hygiene.py", summary=summary)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
