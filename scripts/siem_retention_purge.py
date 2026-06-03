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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db_adapter import get_connection
    conn = get_connection(); cur = conn.cursor()
    total = 0
    for t in TABLES:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE created_at < NOW() - (%s || ' days')::interval", (args.days,))
            n = cur.fetchone()[0]
            if not args.dry_run and n:
                cur.execute(f"DELETE FROM {t} WHERE created_at < NOW() - (%s || ' days')::interval", (args.days,))
                conn.commit()
            total += n
            print(f"[siem-purge] {t}: {'would purge' if args.dry_run else 'purged'} {n} rows older than {args.days}d")
        except Exception as e:
            print(f"[siem-purge] {t}: error {e}")
            conn.rollback()
    conn.close()
    print(f"[siem-purge] {'DRY-RUN ' if args.dry_run else ''}total {total} rows over {args.days}d retention")


if __name__ == "__main__":
    main()
