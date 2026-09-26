#!/usr/bin/env python3
"""Repair the Aegis ensemble job queue after the 2026-07-08 `lanes` outage.

The worker's claim SQL returns ``lanes``; the live table never got the column,
so every claim raised and nothing ran from 2026-07-08 11:12 onward. This:

1. applies the idempotent ``ADD COLUMN IF NOT EXISTS lanes`` from
   create_inference_schema.py;
2. marks stale ``queued`` jobs (older than ENSEMBLE_STALE_JOB_DAYS) and orphaned
   ``running`` jobs (started before the same cutoff) as ``expired`` -- an UPDATE,
   never a delete -- after writing every affected id to an archive file.

Dry run by default; ``--apply`` writes. Recent jobs stay queued for the worker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ADD_LANES = "ALTER TABLE inference_ensemble_jobs ADD COLUMN IF NOT EXISTS lanes JSONB"
EXPIRE_REASON = "expired: worker could not claim (missing lanes column) 2026-07-08..repair"


def _load_env() -> None:
    f = ROOT / ".env"
    if not f.is_file():
        return
    for raw in f.read_text(errors="ignore").splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def stale_days() -> int:
    return int(os.environ.get("ENSEMBLE_STALE_JOB_DAYS", "3"))


def select_stale_sql() -> str:
    return (
        "SELECT id, status, target_type, requested_at, started_at FROM inference_ensemble_jobs "
        "WHERE (status='queued' AND requested_at < now() - make_interval(days => %s)) "
        "OR (status='running' AND COALESCE(started_at, requested_at) < now() - make_interval(days => %s)) "
        "ORDER BY id"
    )


def expire_sql() -> str:
    return (
        "UPDATE inference_ensemble_jobs SET status='expired', error=%s, finished_at=now() "
        "WHERE id = ANY(%s) AND status IN ('queued','running')"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--archive-dir", default=str(ROOT / "data" / "audit"))
    a = ap.parse_args(argv)
    _load_env()
    from db_adapter import _execute

    days = stale_days()
    cols = _execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='inference_ensemble_jobs'",
        fetch="all") or []
    has_lanes = any(r["column_name"] == "lanes" for r in cols)
    rows = _execute(select_stale_sql(), (days, days), fetch="all") or []
    ids = [int(r["id"]) for r in rows]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    plan = {
        "mode": "apply" if a.apply else "dry_run",
        "lanes_column_present": has_lanes,
        "ddl": None if has_lanes else ADD_LANES,
        "stale_days": days,
        "expire_count": len(ids),
        "expire_by_status": by_status,
    }
    if not a.apply:
        print(json.dumps(plan, indent=2, default=str))
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = Path(a.archive_dir) / f"ensemble_job_expiry_{stamp}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps({"plan": plan, "rows": rows}, indent=1, default=str), encoding="utf-8")
    if not has_lanes:
        _execute(ADD_LANES, fetch=None)
    if ids:
        _execute(expire_sql(), (EXPIRE_REASON, ids), fetch=None)
    plan["archive"] = str(archive)
    print(json.dumps(plan, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
