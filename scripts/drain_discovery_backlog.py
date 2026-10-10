#!/usr/bin/env python3
"""drain_discovery_backlog.py — advance the stuck Hermes discovery inbox.

Watches the gap found in the 2026-08-19 watchlist audit (Gap D): 644 DISCOVERED +
307 CLUSTERED hermes_discovery_candidates sat frozen since 2026-07-05, so the
"what should be added to the watchlist" surface never advanced.

Conservative, deterministic transitions (never fabricates, never auto-promotes to a
trading rail):
  - CLUSTERED + recent + has extracted_symbols  -> READY_FOR_REVIEW  (reviewable)
  - DISCOVERED/CLUSTERED past their TTL          -> ARCHIVED_COLD    (stale, never acted on)

Every transition writes a hermes_discovery_audit TRANSITION row. Operator rows
(is_operator=TRUE) are NEVER touched.

Usage:
    python3 scripts/drain_discovery_backlog.py --dry-run
    python3 scripts/drain_discovery_backlog.py --apply

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` WINS over ``--apply`` (before this change
``--apply --dry-run`` APPLIED); no ``--apply`` is still a dry run. The dry run runs the two selection
SELECTs on a session made READ ONLY at the server, prints a ``DRY-RUN`` report and returns BEFORE the
UPDATE / audit INSERT / commit are reachable. It writes no receipt.

A REAL (``--apply``) run writes LaneRunReceipt@v1 ``<state_root>/data/runtime/drain-discovery-backlog_last.json``
(``ok_at`` only on success). Exit codes: 0 = ran (nothing to promote or archive is a finding, still 0);
1 = the run failed (DB unavailable or any statement raised -- the batch is one transaction, so nothing
is half-applied); 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LANE_ID = "drain-discovery-backlog"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.drain_discovery_backlog
        from scripts.lib import lane_last_receipt as lr
    return lr


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def _transition(conn, candidate_id: int, old: str, new: str, note: str) -> None:
    conn.cursor().execute(
        """INSERT INTO hermes_discovery_audit (candidate_id, action, actor, before_json, after_json, notes)
           VALUES (%s, 'TRANSITION', 'system', %s, %s, %s)""",
        (candidate_id, json.dumps({"status": old}), json.dumps({"status": new}), note))


def _select(cur, promote_max: int) -> tuple[list, list]:
    """The two read-only selections -> (to_promote, to_archive)."""
    # 1. Promote CLUSTERED -> READY_FOR_REVIEW when recent + has extracted symbols.
    cur.execute("""
        SELECT id, label, last_seen_at
        FROM hermes_discovery_candidates
        WHERE status = 'CLUSTERED'
          AND is_operator = FALSE
          AND cardinality(extracted_symbols) > 0
          AND last_seen_at > NOW() - INTERVAL '14 days'
        ORDER BY last_seen_at DESC
        LIMIT %s
    """, (promote_max,))
    to_promote = cur.fetchall()

    # 2. Archive DISCOVERED/CLUSTERED past their TTL.
    cur.execute("""
        SELECT id, label, status
        FROM hermes_discovery_candidates
        WHERE status IN ('DISCOVERED', 'CLUSTERED')
          AND is_operator = FALSE
          AND last_seen_at < NOW() - (ttl_days * INTERVAL '1 day')
    """)
    to_archive = cur.fetchall()

    print(f"[discovery-drain] promote CLUSTERED->READY_FOR_REVIEW: {len(to_promote)}")
    print(f"[discovery-drain] archive stale ->ARCHIVED_COLD: {len(to_archive)}")
    return to_promote, to_archive


def _dry_run(args) -> int:
    """Read-only preview. The UPDATE / audit INSERT / commit are not reachable from here."""
    lr = _receipt_lib()
    try:
        conn = _get_conn()
        lr.enforce_readonly(conn)
        to_promote, to_archive = _select(conn.cursor(), args.promote_max)
    except Exception as e:
        print(f"[discovery-drain] DRY-RUN read failed: {type(e).__name__}: {e}")
        return 1
    print("[discovery-drain] DRY-RUN — no changes applied")
    try:
        conn.close()
    except Exception:
        pass
    lr.dry_run_report(
        LANE_ID,
        {"would_promote": len(to_promote), "would_archive": len(to_archive),
         "archive_by_status": {st: sum(1 for r in to_archive if r[2] == st) for st in {r[2] for r in to_archive}}},
        would_write=["hermes_discovery_candidates (UPDATE status) x would_promote+would_archive",
                     "hermes_discovery_audit (INSERT TRANSITION) x would_promote+would_archive"],
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="read + report only; wins over --apply")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--promote-max", type=int, default=200)
    args = ap.parse_args(argv)

    if args.dry_run or not args.apply:
        return _dry_run(args)

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        to_promote, to_archive = _select(cur, args.promote_max)
        for cid, label, _ in to_promote:
            cur.execute(
                """UPDATE hermes_discovery_candidates
                   SET status='READY_FOR_REVIEW', decided_at=NOW(), updated_at=NOW()
                   WHERE id=%s""", (cid,))
            _transition(conn, cid, "CLUSTERED", "READY_FOR_REVIEW", f"backlog drain: {label}")
        for cid, label, old in to_archive:
            cur.execute(
                """UPDATE hermes_discovery_candidates
                   SET status='ARCHIVED_COLD', decided_at=NOW(), updated_at=NOW()
                   WHERE id=%s""", (cid,))
            _transition(conn, cid, old, "ARCHIVED_COLD", f"stale backlog: {label}")
        conn.commit()
        print(f"[discovery-drain] applied: {len(to_promote)} promoted, {len(to_archive)} archived")
        conn.close()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="drain_discovery_backlog.py", error=f"{type(exc).__name__}: {exc}")
        raise
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="drain_discovery_backlog.py",
                          summary={"promoted": len(to_promote), "archived": len(to_archive)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
