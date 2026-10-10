#!/usr/bin/env python3
"""prewarm_eligible_cache.py — pre-warm the analyst /eligible cache out of the request path (cron L573).

Entrypoint for what cron runs today as an inline
``$PY -c "import reporting_engine as r; r.eligible_report_payload(use_cache=False)"``, so the n8n run
allowlist can name one script argv. Same call, same cache file
(``reporting_engine._ELIGIBLE_CACHE`` = data/runtime/analyst_eligible_cache.json, which the served
release symlinks to the persistent state root).

  python3 scripts/prewarm_eligible_cache.py            # live: recompute + write the cache
  python3 scripts/prewarm_eligible_cache.py --dry-run  # read-only: recompute, print, write nothing

Honest exit (the inline form could not give one): eligible_report_payload swallows its own SQL errors
(analyst_report_builder._db_query returns []), and its cache write swallows I/O errors. So a run first
probes the database with a query that RAISES, and afterwards checks that the cache file now holds THIS
run's payload. Either failing exits 1. A real run also writes
data/runtime/prewarm_eligible_cache_last.json (LaneRunReceipt@v1; ok_at only on success).

--dry-run calls eligible_report_payload(use_cache=False, write_cache=False): the same computation with
the cache write unreachable (AGENTS.md §6).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

RECEIPT_NAME = "prewarm_eligible_cache"


def _probe_db(readonly: bool = False) -> None:
    """Raise when the database is unreachable or the watchlist query fails (not swallowed).

    readonly=True also puts this thread's db_adapter session in READ ONLY (dry-run defence in depth).
    """
    from db_adapter import _get_conn

    conn = _get_conn()
    if conn is None:
        raise RuntimeError("no database connection")
    if readonly:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM watchlist_items WHERE status <> 'removed'")
        cur.fetchone()
    finally:
        cur.close()
        conn.rollback()


def _summary(payload: dict) -> dict:
    return {k: payload.get(k) for k in ("count", "watchlist_count", "needs_refresh", "stale_days")}


def run(dry_run: bool = False) -> dict:
    import reporting_engine as r

    _probe_db(readonly=dry_run)
    payload = r.eligible_report_payload(use_cache=False, write_cache=not dry_run)
    out = _summary(payload)
    if dry_run:
        out.update(dry_run=True, would_write=str(r._ELIGIBLE_CACHE))
        return out
    try:
        written = json.loads(Path(r._ELIGIBLE_CACHE).read_text())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"cache not readable after write: {type(exc).__name__}: {exc}") from exc
    if written.get("_cached_at") != payload.get("_cached_at"):
        raise RuntimeError("cache write did not land (file holds a different payload)")
    out["cache_path"] = str(r._ELIGIBLE_CACHE)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pre-warm the analyst /eligible cache.")
    ap.add_argument("--dry-run", action="store_true", help="recompute and print; write nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        try:
            print(json.dumps(run(dry_run=True), indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print(f"[eligible-prewarm] DRY RUN failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        res = run()
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"[eligible-prewarm] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_receipt(RECEIPT_NAME, ok=True, summary=res, started_at=started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
