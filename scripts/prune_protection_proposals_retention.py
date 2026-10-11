#!/usr/bin/env python3
"""Prune old SUPERSEDED protection adjustment rows (bounded retention)."""
from __future__ import annotations

import argparse
import os

RETENTION_DAYS = int(os.getenv("PROTECTION_PROPOSAL_RETENTION_DAYS", "30"))


def prune(conn=None, *, dry_run: bool = False, archive: bool = True) -> dict:
    """2026-10-11 (retention-all-managed): archive-first via lib.retention_archive.managed_purge; a dry
    run only counts. ``archive=False`` (``--no-archive``) is the inherited hard DELETE."""
    import sys
    from pathlib import Path
    _scripts = str(Path(__file__).resolve().parent)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    from lib.retention_archive import managed_purge
    from db_adapter import _get_conn
    conn = conn or _get_conn()
    r = managed_purge(conn, table="paper_protection_adjustment_proposals",
                      where_sql="t.status = 'SUPERSEDED' AND t.created_at < now() - (%s * interval '1 day')",
                      params=(RETENTION_DAYS,), label=f"superseded_{RETENTION_DAYS}d",
                      writer="prune_protection_proposals_retention", apply=not dry_run, archive=archive)
    return {"retention_days": RETENTION_DAYS, "eligible": r["eligible"], "deleted": r["deleted"],
            "archived": r["archived"], "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-archive", action="store_true", help="rollback lever: hard DELETE without archive")
    args = ap.parse_args()
    import json
    print(json.dumps(prune(dry_run=args.dry_run, archive=not args.no_archive), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())