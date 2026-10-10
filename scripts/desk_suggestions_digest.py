#!/usr/bin/env python3
"""desk_suggestions_digest.py — surface the pending desk "curate-in" backlog.

Closes Gap B from the 2026-08-19 watchlist audit: desk-sourced directives reach
watch_directive_hits but land as STAGED_FOR_REVIEW because _auto_apply has no hit-rate
calibration (hr=None), so auto_apply_gate never promotes them. The result is a large
STAGED_FOR_REVIEW pileup the operator never sees.

This script prints a daily digest of the pending backlog (counts by surfaced_by + the
newest staged suggestions with their reason) so the operator can one-tap promote via
the existing endpoint instead of the suggestions being silently drained.

It does NOT auto-promote — that stays an operator policy decision (see
docs/cio/TWO_WAY_WATCHLIST_CURATION.md). It only reads and surfaces.

Usage:
    python3 scripts/desk_suggestions_digest.py
    python3 scripts/desk_suggestions_digest.py --top 25
    python3 scripts/desk_suggestions_digest.py --dry-run

Receipts (n8n refactor wave 3, 2026-10-10). A REAL run keeps its existing contract unchanged:
``run_with_receipt`` writes ScheduledJobReceipt@v1 ``data/runtime/desk_suggestions_digest_last.json``
(the lane_registry / n8n_run_allowlist ``output_signal``; ``--receipt PATH`` still overrides it). That
file is NOT LaneRunReceipt-shaped (no lane_id/status/started_at/finished_at/mode), so a real run ALSO
writes LaneRunReceipt@v1 ``data/runtime/desk-suggestions-digest_last.json`` (``ok_at`` only on success).
``--dry-run`` runs the same SELECTs on a session made READ ONLY at the server, prints the digest and a
``DRY-RUN`` report, and is never wrapped by ``run_with_receipt``: it writes neither receipt.

Exit codes: 0 = ran (an empty backlog is a finding, still 0); 1 = the run failed (DB unavailable or a
query raised); 2 = usage error (rejected before any receipt is written).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LANE_ID = "desk-suggestions-digest"
LEGACY_RECEIPT_SCRIPT = "desk_suggestions_digest"  # ScheduledJobReceipt@v1 file name (unchanged contract)


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.desk_suggestions_digest
        from scripts.lib import lane_last_receipt as lr
    return lr


def _parser(with_receipt: bool = False) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true",
                    help="read + print only (READ ONLY session); writes no receipt")
    if with_receipt:  # consumed by run_with_receipt before main() parses
        ap.add_argument("--receipt", help="ScheduledJobReceipt path (default data/runtime/desk_suggestions_digest_last.json)")
    return ap


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def main(argv=None) -> dict:
    args = _parser().parse_args(argv)

    conn = _get_conn()
    if args.dry_run:
        _receipt_lib().enforce_readonly(conn)
    cur = conn.cursor()

    cur.execute("""
        SELECT COALESCE(surfaced_by, 'unknown') AS src, count(*) AS pending,
               max(surfaced_at) AS newest
        FROM watch_directive_hits
        WHERE promotion_status = 'STAGED_FOR_REVIEW'
        GROUP BY src ORDER BY pending DESC
    """)
    by_src = cur.fetchall()

    cur.execute("""
        SELECT symbol, surfaced_by, hit_reason, surfaced_at
        FROM watch_directive_hits
        WHERE promotion_status = 'STAGED_FOR_REVIEW'
        ORDER BY surfaced_at DESC
        LIMIT %s
    """, (args.top,))
    top = cur.fetchall()

    total = sum(r[1] for r in by_src)
    print(f"[desk-digest] pending STAGED_FOR_REVIEW suggestions: {total}")
    for src, n, newest in by_src:
        age = (__import__("datetime").datetime.now().astimezone() - newest).days if newest else None
        print(f"  {src:<12} {n:>7}  newest {age}d ago" if age is not None else f"  {src:<12} {n:>7}")
    print(f"\n  Newest {len(top)} staged suggestions:")
    for sym, src, reason, at in top:
        print(f"    {sym:<6} [{src:<10}] {(reason or '')[:70]}")

    conn.close()
    if args.dry_run:
        _receipt_lib().dry_run_report(
            LANE_ID,
            {"pending": total, "sources": len(by_src), "top_listed": len(top)},
            would_write=["data/runtime/desk_suggestions_digest_last.json (ScheduledJobReceipt@v1)"],
        )
    return {"pending": total, "by_src": by_src, "top": top}


def cli(argv=None) -> int:
    """Cron entry point. Usage errors exit 2 before any receipt; --dry-run never reaches a receipt."""
    raw = list(sys.argv[1:] if argv is None else argv)
    args = _parser(with_receipt=True).parse_args(raw)
    if args.dry_run:
        main(["--top", str(args.top), "--dry-run"])
        return 0

    from lib.scheduled_job_receipt import run_with_receipt
    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    original = sys.argv[:]
    sys.argv[:] = [original[0], *raw]
    try:
        result = run_with_receipt(main, script=LEGACY_RECEIPT_SCRIPT, root=PROJECT_ROOT)
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="desk_suggestions_digest.py", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        sys.argv[:] = original
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="desk_suggestions_digest.py",
                          summary={"pending": result.get("pending"), "sources": len(result.get("by_src") or []),
                                   "top_listed": len(result.get("top") or [])})
    return 0


if __name__ == "__main__":
    sys.exit(cli())
