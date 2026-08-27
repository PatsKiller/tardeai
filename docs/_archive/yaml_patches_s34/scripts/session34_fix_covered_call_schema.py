#!/usr/bin/env python3
"""
session34_fix_covered_call_schema.py
====================================
Hotfix: the covered_call_scoring writer is INSERTing the string '1.5-3.0'
(a range expression from the LLM) into a NUMERIC column. This script:

  1. Runs the diagnostic to find the actual table and column
  2. Shows the user which column needs widening
  3. With --apply, runs ALTER TABLE to widen that column to TEXT
  4. Creates a paired NUMERIC column (column_low, column_high) so
     downstream consumers can still get numeric min/max if they want
  5. Logs the change to backups/session34_schema_changes.log

DOES NOT run automatically — you must specify --column NAME after reading
the diagnostic output. This is deliberately friction-y because schema
changes are irreversible.

Usage:
    # 1. First, run the diagnostic to see what we're working with
    python3 scripts/session34_diagnose.py --output backups/session34_diagnose.md
    less backups/session34_diagnose.md
    # ^ look at Section 1 for the column with type 'numeric' that received '1.5-3.0'

    # 2. Then run this with the specific table+column
    python3 scripts/session34_fix_covered_call_schema.py \\
        --table covered_call_scoring_results \\
        --column strike_band \\
        --dry-run

    # 3. Apply
    python3 scripts/session34_fix_covered_call_schema.py \\
        --table covered_call_scoring_results \\
        --column strike_band \\
        --apply
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed.")
    sys.exit(1)


def preflight_check():
    holdings_file = Path("data/portfolios/state/holdings.json")
    with open(holdings_file) as f:
        d = json.load(f)
    total = d.get("portfolio_totals", {}).get("total_value", 0)
    count = len(d.get("holdings", []))
    print(f"  Holdings: ${total:,.0f} / {count} positions")
    assert total > 1_000_000 and count >= 30
    return True


def get_db_conn():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", os.environ.get("DB_NAME", "tradeai")),
        user=os.environ.get("PGUSER", os.environ.get("DB_USER", "johnclaw")),
        password=os.environ.get("PGPASSWORD", os.environ.get("DB_PASSWORD", "")),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True, help="Table name (from diagnostic Section 1)")
    parser.add_argument("--column", required=True, help="Column to widen to TEXT")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"Session 34 covered_call schema fix — {mode}")
    print(f"Target: {args.table}.{args.column}")
    print("=" * 70)

    if not args.skip_preflight:
        print("\nPre-flight:")
        preflight_check()

    conn = get_db_conn()
    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Confirm table and column exist
            cur.execute("""
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
            """, (args.table, args.column))
            row = cur.fetchone()
            if not row:
                print(f"ERROR: column {args.table}.{args.column} not found")
                sys.exit(1)
            print(f"\nCurrent: {args.table}.{args.column} = {row['data_type']}")

            if row['data_type'] in ('text', 'character varying'):
                print("Already TEXT/varchar. No change needed.")
                sys.exit(0)

            current_type = row['data_type']

            print(f"\nProposed change:")
            print(f"  ALTER TABLE {args.table}")
            print(f"    ALTER COLUMN {args.column} TYPE TEXT USING {args.column}::TEXT;")
            print(f"  ALTER TABLE {args.table}")
            print(f"    ADD COLUMN IF NOT EXISTS {args.column}_low NUMERIC,")
            print(f"    ADD COLUMN IF NOT EXISTS {args.column}_high NUMERIC;")

            if args.apply:
                # Backup the table data first (sample, not full)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = Path("backups") / f"session34_schema_{ts}"
                backup_dir.mkdir(parents=True, exist_ok=True)

                cur.execute(f"SELECT COUNT(*) AS cnt FROM {args.table}")
                row_count = cur.fetchone()['cnt']
                print(f"\nRow count in {args.table}: {row_count}")

                if row_count > 0:
                    cur.execute(f"SELECT * FROM {args.table}")
                    rows = cur.fetchall()
                    backup_file = backup_dir / f"{args.table}_pre_alter.json"
                    backup_file.write_text(json.dumps(
                        [dict(r) for r in rows], default=str, indent=2,
                    ))
                    print(f"Data backup: {backup_file}")

                # Apply the ALTER
                cur.execute(f"""
                    ALTER TABLE {args.table}
                    ALTER COLUMN {args.column} TYPE TEXT USING {args.column}::TEXT
                """)
                cur.execute(f"""
                    ALTER TABLE {args.table}
                    ADD COLUMN IF NOT EXISTS {args.column}_low NUMERIC,
                    ADD COLUMN IF NOT EXISTS {args.column}_high NUMERIC
                """)

                # Log the change
                log_file = Path("backups") / "session34_schema_changes.log"
                log_file.write_text(
                    (log_file.read_text() if log_file.exists() else "") +
                    f"\n{datetime.now().isoformat(timespec='seconds')}: "
                    f"ALTER TABLE {args.table} ALTER COLUMN {args.column} {current_type} -> TEXT; "
                    f"ADD {args.column}_low NUMERIC, {args.column}_high NUMERIC\n"
                )
                print(f"Schema change log: {log_file}")

                conn.commit()
                print("\nApplied and committed.")
            else:
                conn.rollback()
                print("\nDry-run rolled back.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
