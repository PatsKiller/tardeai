#!/usr/bin/env python3
"""Quarantine analyst_consensus_history rows fabricated by the Finviz column shift.

WHAT HAPPENED
-------------
finviz_enrichment.py mapped the Finviz export by column position. Finviz inserted
"Performance (3 Years)", "(5 Years)" and "(10 Years)" into view 141, shifting every
later field right by three. Index 10 was labelled "recom"; it actually carried
"Performance (10 Years)". The classifier then mapped that ten-year return onto a
1-5 analyst scale, and because low numbers meant bullish, the labels came out
ANTI-correlated with reality: a stock down -100% over ten years was published as
"Strong Buy".

Measured 2026-09-13: 131,050 of 132,894 rows (98.6%) are affected, spanning
2026-04 to 2026-09-10. Fixed forward by PR #988 (refuse off-scale values) and by
the header-name column map. Neither repairs rows already written.

WHAT THIS DOES
--------------
Nothing is deleted. Ever.

  1. Copies every affected row, whole and unmodified, into
     analyst_consensus_history_quarantine_20260913.
  2. In the live table, sets ONLY the two derived columns -- recom_score and
     analyst_rating -- to NULL on those rows. recom_raw is preserved, so the
     original provider string remains readable and the archive is redundant
     rather than load-bearing.
  3. Leaves a tripwire view that reports any reappearance.

Consumers that read analyst_rating (portfolio_signals.py gates `favorable` on it)
then see NO rating rather than an inverted one. Missing data is recoverable;
confidently wrong data is not.

REVERSAL
--------
    UPDATE analyst_consensus_history a
       SET recom_score = q.recom_score, analyst_rating = q.analyst_rating
      FROM analyst_consensus_history_quarantine_20260913 q
     WHERE a.id = q.id;

USAGE
-----
    python scripts/quarantine_fabricated_analyst_ratings.py            # dry run
    python scripts/quarantine_fabricated_analyst_ratings.py --apply    # execute
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2

QUARANTINE_TABLE = "analyst_consensus_history_quarantine_20260913"

# A Finviz "Recom" is a 1-5 analyst scale. A row whose score falls outside that
# range cannot be a recommendation, whatever the column was labelled.
AFFECTED_PREDICATE = "recom_score IS NOT NULL AND NOT (recom_score BETWEEN 1 AND 5)"


def _env_from_runtime() -> dict:
    """Read DB settings the way the rest of the fleet does."""
    env = {}
    runtime = Path("/run/user/1000/tradeai/env")
    if runtime.exists():
        for line in runtime.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip("\"'")
    for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not env.get(k)]
    if missing:
        raise SystemExit(
            f"ERROR: database settings unavailable: {missing}. Refusing to guess or fall back to an ambient ~/.pgpass."
        )
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute; without it the script only reports")
    args = ap.parse_args()

    env = _env_from_runtime()
    conn = psycopg2.connect(
        host=env["DB_HOST"],
        port=env.get("DB_PORT", 5432),
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
    )
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(f"SELECT count(*) FROM analyst_consensus_history WHERE {AFFECTED_PREDICATE}")
    affected = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM analyst_consensus_history")
    total = cur.fetchone()[0]
    cur.execute(
        f"SELECT min(snapshot_date), max(snapshot_date), min(recom_score), max(recom_score) "
        f"FROM analyst_consensus_history WHERE {AFFECTED_PREDICATE}"
    )
    lo_d, hi_d, lo_s, hi_s = cur.fetchone()

    print("Fabricated analyst ratings — quarantine")
    print("-" * 64)
    print(f"  rows in table          : {total:,}")
    print(f"  affected (off 1-5)     : {affected:,}  ({100.0 * affected / total:.1f}%)")
    print(f"  snapshot_date range    : {lo_d} .. {hi_d}")
    print(f"  recom_score range      : {lo_s} .. {hi_s}")
    print(f"  quarantine table       : {QUARANTINE_TABLE}")
    print(f"  columns nulled in live : recom_score, analyst_rating (recom_raw kept)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to execute.")
        cur.execute(
            f"SELECT symbol, recom_raw, recom_score, analyst_rating, snapshot_date "
            f"FROM analyst_consensus_history WHERE {AFFECTED_PREDICATE} "
            f"ORDER BY snapshot_date DESC LIMIT 5"
        )
        print("\n  sample of what would be quarantined:")
        for r in cur.fetchall():
            print(f"    {r[0]:<8} raw={str(r[1]):<10} score={str(r[2]):<10} rating={str(r[3]):<12} {r[4]}")
        conn.rollback()
        return 0

    try:
        # 1. Archive whole rows, unmodified. Idempotent: skip ids already held.
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {QUARANTINE_TABLE} (LIKE analyst_consensus_history INCLUDING DEFAULTS)"
        )
        cur.execute(
            f"INSERT INTO {QUARANTINE_TABLE} "
            f"SELECT * FROM analyst_consensus_history a "
            f"WHERE {AFFECTED_PREDICATE} "
            f"  AND NOT EXISTS (SELECT 1 FROM {QUARANTINE_TABLE} q WHERE q.id = a.id)"
        )
        archived = cur.rowcount

        cur.execute(f"SELECT count(*) FROM {QUARANTINE_TABLE}")
        held = cur.fetchone()[0]
        if held < affected:
            raise RuntimeError(
                f"archive holds {held:,} rows but {affected:,} are affected — refusing to null the live columns"
            )

        # 2. Null ONLY the derived columns, and only where the archive has the row.
        cur.execute(
            f"UPDATE analyst_consensus_history a "
            f"SET recom_score = NULL, analyst_rating = NULL "
            f"WHERE {AFFECTED_PREDICATE} "
            f"  AND EXISTS (SELECT 1 FROM {QUARANTINE_TABLE} q WHERE q.id = a.id)"
        )
        nulled = cur.rowcount

        # 3. Tripwire: fires if off-scale values ever reappear in the live table.
        cur.execute(
            "CREATE OR REPLACE VIEW analyst_rating_scale_tripwire AS "
            "SELECT count(*) AS off_scale_rows, max(snapshot_date) AS newest "
            "FROM analyst_consensus_history "
            "WHERE recom_score IS NOT NULL AND NOT (recom_score BETWEEN 1 AND 5)"
        )

        conn.commit()
        print(f"\n  archived           : {archived:,} rows (table now holds {held:,})")
        print(f"  live rows cleared  : {nulled:,}")
        print("  tripwire view      : analyst_rating_scale_tripwire")
        print("\nAPPLIED. Reverse with the UPDATE in this file's docstring.")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"\nROLLED BACK — nothing changed: {exc}", file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
