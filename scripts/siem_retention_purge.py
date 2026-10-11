#!/usr/bin/env python3
"""SIEM retention purge — keep only the last N days (default 14) of alert/event noise.

The SIEM dashboard reads alert_events + system_health_events (+ telegram). system_health_events
is a firehose (~500–1100 rows/day from the */5 health agent) that was never pruned, so it grows
unbounded. This enforces a rolling retention window on the alert/event tables.

    python3 scripts/siem_retention_purge.py            # purge > 14 days
    python3 scripts/siem_retention_purge.py --days 30 --dry-run
Cron: daily ~3:10 AM.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Alert/event tables safe to age out (NOT trade/journal/audit-of-record tables).
TABLES = ["system_health_events", "alert_events"]


def purge(conn, days: int, *, apply: bool, archive: bool = True) -> list[dict]:
    """2026-10-11 (retention-all-managed): archive-first through lib.retention_archive.managed_purge --
    every purged row lands in the row-archive root (retention_archive.archive_root) with a sha256 manifest and a tripwire
    BEFORE its DELETE; a dry run only counts. Registered in config/data_retention_policy.json purge_paths."""
    from lib.retention_archive import managed_purge
    out = []
    for t in TABLES:
        try:
            out.append(managed_purge(conn, table=t, where_sql="t.created_at < NOW() - (%s || ' days')::interval",
                                     params=(days,), label=f"siem_{days}d", writer="siem_retention_purge",
                                     apply=apply, archive=archive))
        except Exception as e:  # noqa: BLE001 -- one table failing must not hide the other
            conn.rollback()
            out.append({"table": t, "error": f"{type(e).__name__}: {e}"[:200]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-archive", action="store_true",
                    help="rollback lever: the inherited hard DELETE (no archive). Default archives first.")
    args = ap.parse_args()

    from db_adapter import get_connection
    conn = get_connection()
    if args.dry_run:
        conn.set_session(readonly=True)
    total, failed = 0, 0
    for r in purge(conn, args.days, apply=not args.dry_run, archive=not args.no_archive):
        if r.get("error"):
            failed += 1
            print(f"[siem-purge] {r['table']}: error {r['error']}")
            continue
        n = r["eligible"] if args.dry_run else r["deleted"]
        total += n
        verb = "would archive+purge" if args.dry_run and r["archive"] else ("would purge" if args.dry_run else "purged")
        print(f"[siem-purge] {r['table']}: {verb} {n} rows older than {args.days}d"
              + (f" (archived {r['archived']})" if not args.dry_run else ""))
    conn.close()
    print(f"[siem-purge] {'DRY-RUN ' if args.dry_run else ''}total {total} rows over {args.days}d retention")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
