#!/usr/bin/env python3
"""hermes_score_history_retention.py — RETIRED 2026-10-21 (operator D4.2): deletes nothing.

Was: thinned hermes_score_history older than --days to one row per (symbol, 6 h bucket) with an unarchived
row delete (audit 2026-07-02), run as step score_history_retention of config/pipelines/hermes_learning.json.

Now: db_retention is the only owner of hermes_score_history (config/data_retention_policy.json: DELETE 21 d,
archive_first; nightly platform maintenance). Every row older than 21 d is archived (jsonl.gz + manifest +
tripwire) and then deleted there, so this step never saw a row it could thin. The step stays in the manifest
(its id is compiled into the deployed n8n fabric workflow tradeai-fabric-hermes-learning as a blocked step);
it only COUNTS and reports the owner, with --apply or without. Lane registry row hermes-score-history-retention
is RETIRED (docs/ops/LANE_REGISTRY_AND_RETIREMENT_CONVENTION.md).

  python3 scripts/hermes_score_history_retention.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

RETIRED = "2026-10-21"
OWNER = "db_retention (config/data_retention_policy.json hermes_score_history, archive-first)"


def run(days: int = 90, apply: bool = False, conn=None) -> dict:
    """Count only. ``apply`` is accepted for the unchanged manifest command and changes nothing."""
    if conn is None:
        from db_adapter import _get_conn

        conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM hermes_score_history")
    rows = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM hermes_score_history WHERE scored_at < NOW() - (%s || ' days')::interval",
        (int(days),),
    )
    older = cur.fetchone()[0]
    out = {
        "ok": True,
        "retired": RETIRED,
        "owner": OWNER,
        "apply_requested": bool(apply),
        "retention_days": days,
        "rows_before": rows,
        "rows_older_than_window": older,
        "rows_deleted": 0,
        "rows_after": rows,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--apply", action="store_true", help="accepted and ignored: RETIRED, deletes nothing")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(days=args.days, apply=args.apply and not args.dry_run)


if __name__ == "__main__":
    main()
