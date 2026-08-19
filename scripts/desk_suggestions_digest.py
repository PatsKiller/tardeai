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
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    conn = _get_conn()
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
    return {"pending": total, "by_src": by_src, "top": top}


if __name__ == "__main__":
    main()
