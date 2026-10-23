#!/usr/bin/env python3
"""reconcile_directive_watch_flag.py — clear ``watchlist_items.in_directive_watch`` where no ACTIVE operator-created
directive matches (operator-approved 2026-10-22: "Yes, I agree with your recommendations.").

The flag's writer and the clearing rule live in ``scripts/directive_promotion.py`` (one writer per store); this file
is only the operator's door to it.

  python3 scripts/reconcile_directive_watch_flag.py                 # DRY RUN (default): counts before/after, breakdown
  python3 scripts/reconcile_directive_watch_flag.py --json          # the same, one JSON object
  python3 scripts/reconcile_directive_watch_flag.py --apply --expect-clear N
        # backup every before-value to $STATE/data/backups/directive_watch_flag/reconcile-<UTC>.jsonl, then clear;
        # refuses unless N equals the plan's clear_rows (copy N from the dry run) so the apply does what was reviewed
  python3 scripts/reconcile_directive_watch_flag.py --restore <backup.jsonl> [--apply]   # rollback (dry unless --apply)

The dry run uses a READ ONLY session (lib.lane_last_receipt.enforce_readonly) and writes nothing. An apply writes the
backup, the UPDATE (in_directive_watch, updated_at only — never a delete), and the marker
data/runtime/directive_watch_flag_reconcile_last.json, whose presence lets watch_directives_service keep the flag
reconciled incrementally afterwards. No broker, no send, no model call. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

MARKER_NAME = "directive_watch_flag_reconcile_last.json"
BACKUP_REL = "data/backups/directive_watch_flag"


def backup_dir() -> Path:
    from lib.persistent_state_root import resolve_durable_dir
    return Path(resolve_durable_dir(BACKUP_REL, PROJECT_ROOT))


def marker_path() -> Path:
    from lib.lane_last_receipt import runtime_dir
    return runtime_dir() / MARKER_NAME


#: One servicer pass clears at most this many rows (a burst of expiries/archives spreads over runs).
INCREMENTAL_MAX_CLEAR = 200


def incremental_reconcile(conn, *, dry: bool) -> dict:
    """watch_directives_service's pass: keep the flag reconciled — ONLY after the operator's one-time apply.

    Before the marker exists (the baseline clear has not been applied by the operator) this does nothing, so
    deploying the code changes no existing row. Afterwards it clears at most INCREMENTAL_MAX_CLEAR rows whose
    operator directive expired or was archived since, backup first (one file per UTC day)."""
    if not marker_path().exists():
        return {"skipped": "baseline_not_applied"}
    if dry:
        return {"skipped": "dry_run"}
    import directive_promotion as dp
    plan = dp.plan_directive_watch_flag_reconcile(conn.cursor())
    if not plan.get("clear"):
        return {"cleared": 0, "attempted": 0, "backup": None}
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return dp.apply_directive_watch_flag_reconcile(conn, plan, backup_path=backup_dir() / f"incremental-{day}.jsonl",
                                                   max_clear=INCREMENTAL_MAX_CLEAR, reason="servicer_incremental")


def _summary(plan: dict) -> dict:
    return {k: plan[k] for k in ("before", "after", "clear_rows", "clear_symbols", "by_directive", "sample",
                                  "creators")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--expect-clear", type=int, default=None,
                    help="required with --apply: the clear_rows the dry run printed")
    ap.add_argument("--restore", default=None, help="a backup .jsonl to restore (dry unless --apply)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    import directive_promotion as dp
    from db_adapter import _get_conn
    conn = _get_conn()

    if a.restore:
        if not a.apply:
            from lib.lane_last_receipt import enforce_readonly
            enforce_readonly(conn)
        res = dp.restore_directive_watch_flag(conn, a.restore, dry_run=not a.apply)
        print(json.dumps({"restore": a.restore, **res}))
        return 0

    if not a.apply:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)
    plan = dp.plan_directive_watch_flag_reconcile(conn.cursor())
    summary = _summary(plan)
    if a.json:
        print(json.dumps(summary, default=str))
    else:
        b, af = plan["before"], plan["after"]
        print(f"in_directive_watch — keep rule: an ACTIVE directive created_by {plan['creators']} matches "
              "(ownership, ticker spec symbol, or a promoted hit)")
        print(f"  before: {b['rows']} rows, {b['symbols']} symbols (watch_universe.directive_symbols)")
        print(f"  after : {af['rows']} rows, {af['symbols']} symbols")
        print(f"  clear : {plan['clear_rows']} rows, {plan['clear_symbols']} symbols")
        print("  cleared rows by owning directive (created_by, status):")
        for r in plan["by_directive"]:
            print(f"    {r['created_by']:<20} {r['directive_status']:<10} {r['rows']}")
        print("  sample: " + ", ".join(f"{r['symbol']}({r['directive_created_by'] or '-'}/{r['directive_status'] or '-'})"
                                       for r in plan["sample"]))
    if not a.apply:
        print(f"DRY RUN: nothing written. To apply: --apply --expect-clear {plan['clear_rows']}",
              file=sys.stderr if a.json else sys.stdout)
        return 0
    if a.expect_clear is None or a.expect_clear != plan["clear_rows"]:
        print(f"REFUSED: --expect-clear {a.expect_clear} != plan clear_rows {plan['clear_rows']} "
              "(re-run the dry run and copy its number)", file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bpath = backup_dir() / f"reconcile-{stamp}.jsonl"
    res = dp.apply_directive_watch_flag_reconcile(conn, plan, backup_path=bpath, reason="operator_apply")
    after = dp.plan_directive_watch_flag_reconcile(conn.cursor())
    marker = {"schema": "DirectiveWatchFlagReconcile@v1", "applied_at": datetime.now(timezone.utc).isoformat(),
              "before": plan["before"], "after": after["before"], "cleared": res["cleared"],
              "attempted": res["attempted"], "backup": res["backup"], "remaining_to_clear": after["clear_rows"],
              "approval": "operator 2026-10-22, in session: \"Yes, I agree with your recommendations.\""}
    from lib.atomic_json_store import atomic_write_json
    atomic_write_json(marker_path(), marker, indent=1)
    print(json.dumps(marker, default=str))
    return 0 if after["clear_rows"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
