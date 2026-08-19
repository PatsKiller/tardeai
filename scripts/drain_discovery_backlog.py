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
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def _transition(conn, candidate_id: int, old: str, new: str, note: str) -> None:
    conn.cursor().execute(
        """INSERT INTO hermes_discovery_audit (candidate_id, action, actor, before_json, after_json, notes)
           VALUES (%s, 'TRANSITION', 'system', %s, %s, %s)""",
        (candidate_id, json.dumps({"status": old}), json.dumps({"status": new}), note))


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--promote-max", type=int, default=200)
    args = ap.parse_args()

    conn = _get_conn()
    cur = conn.cursor()

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
    """, (args.promote_max,))
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

    if args.apply:
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
    else:
        print("[discovery-drain] DRY-RUN — no changes applied")

    conn.close()
    return {"promoted": len(to_promote), "archived": len(to_archive), "dry_run": not args.apply}


if __name__ == "__main__":
    main()
