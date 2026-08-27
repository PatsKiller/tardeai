#!/usr/bin/env python3
"""
session34_queue_triage.py
=========================
Resets stuck 'running' jobs in llm_overnight_queue and (optionally) marks
all pending covered_call_scoring jobs as 'skipped' so they don't crash
tonight's 23:00 auto window.

Always read holdings first (Iron Rule). Always show dry-run first.

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/session34_queue_triage.py --dry-run
    python3 scripts/session34_queue_triage.py --apply
    python3 scripts/session34_queue_triage.py --apply --skip-covered-call
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary --break-system-packages")
    sys.exit(1)


def preflight_check():
    """Iron Rule: never operate without verifying holdings state."""
    holdings_file = Path("data/portfolios/state/holdings.json")
    if not holdings_file.exists():
        print(f"FAIL: holdings.json not found at {holdings_file}")
        return False
    with open(holdings_file) as f:
        d = json.load(f)
    total = d.get("portfolio_totals", {}).get("total_value", 0)
    count = len(d.get("holdings", []))
    print(f"  Holdings: ${total:,.0f} / {count} positions")
    if total < 1_000_000:
        print(f"FAIL: holdings ${total:,.0f} too low — ABORT")
        return False
    if count < 30:
        print(f"FAIL: only {count} positions — ABORT")
        return False
    return True


def get_db_conn():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", os.environ.get("DB_HOST", "localhost")),
        port=int(os.environ.get("PGPORT", os.environ.get("DB_PORT", "5432"))),
        dbname=os.environ.get("PGDATABASE", os.environ.get("DB_NAME", "tradeai")),
        user=os.environ.get("PGUSER", os.environ.get("DB_USER", "johnclaw")),
        password=os.environ.get("PGPASSWORD", os.environ.get("DB_PASSWORD", "")),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-covered-call", action="store_true",
                        help="Also mark all pending covered_call_scoring jobs as 'skipped'")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"Session 34 queue triage — {mode}")
    print("=" * 70)

    if not args.skip_preflight:
        print("\nPre-flight (Iron Rule):")
        if not preflight_check():
            sys.exit(1)

    conn = get_db_conn()
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Stuck running jobs
            cur.execute("""
                SELECT id, job_type, symbol, started_at,
                       EXTRACT(EPOCH FROM (NOW() - started_at)) AS age_sec
                FROM llm_overnight_queue
                WHERE status = 'running'
                ORDER BY id
            """)
            running = cur.fetchall()

            print(f"\n[1] Stuck 'running' jobs: {len(running)}")
            for r in running:
                age = r.get('age_sec') or 0
                print(f"    id={r['id']} {r['job_type']:<25} {r.get('symbol','')!s:<15} age={age:.0f}s")

            if running:
                if args.apply:
                    cur.execute("""
                        UPDATE llm_overnight_queue
                        SET status = 'failed',
                            error_message = COALESCE(error_message,'') ||
                                            ' [session34_triage: stuck running, reset to failed]',
                            finished_at = NOW()
                        WHERE status = 'running'
                        RETURNING id
                    """)
                    reset_ids = [r['id'] for r in cur.fetchall()]
                    print(f"    -> Reset {len(reset_ids)} job(s) to 'failed': {reset_ids}")
                else:
                    print(f"    -> Would reset {len(running)} job(s) to 'failed'")

            # 2. Optional: skip pending covered_call_scoring jobs
            if args.skip_covered_call:
                cur.execute("""
                    SELECT id, symbol FROM llm_overnight_queue
                    WHERE status = 'pending' AND job_type = 'covered_call_scoring'
                    ORDER BY id
                """)
                cc_pending = cur.fetchall()
                print(f"\n[2] Pending covered_call_scoring jobs: {len(cc_pending)}")
                if cc_pending:
                    for r in cc_pending[:10]:
                        print(f"    id={r['id']} symbol={r.get('symbol','')}")
                    if len(cc_pending) > 10:
                        print(f"    ... and {len(cc_pending) - 10} more")

                    if args.apply:
                        cur.execute("""
                            UPDATE llm_overnight_queue
                            SET status = 'skipped',
                                error_message = '[session34_triage: blocked pending schema fix for 1.5-3.0 range]',
                                finished_at = NOW()
                            WHERE status = 'pending' AND job_type = 'covered_call_scoring'
                            RETURNING id
                        """)
                        skipped = [r['id'] for r in cur.fetchall()]
                        print(f"    -> Skipped {len(skipped)} job(s)")
                    else:
                        print(f"    -> Would skip {len(cc_pending)} pending covered_call job(s)")

            # 3. Summary of queue state after (or current if dry-run)
            cur.execute("""
                SELECT status, COUNT(*) AS cnt
                FROM llm_overnight_queue
                GROUP BY status
                ORDER BY status
            """)
            print(f"\n[3] Queue state {'after triage' if args.apply else '(unchanged)'}:")
            for r in cur.fetchall():
                print(f"    {r['status']:<12} {r['cnt']:>6}")

        if args.apply:
            conn.commit()
            print("\nCommitted.")
        else:
            conn.rollback()
            print("\nDry-run rolled back. Re-run with --apply to commit.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
