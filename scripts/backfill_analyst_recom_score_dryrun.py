#!/usr/bin/env python3
"""LQ-20261107-185 — classify every NULL ``analyst_consensus_history.recom_score`` by cause. DRY RUN ONLY.

WHY THERE IS NO --apply
-----------------------
The obvious "backfill" is to recompute ``recom_score`` from ``recom_raw``, the provider string kept
when the fabricated ratings were quarantined. It is the wrong move. For nearly every NULL row
``recom_raw`` is a ten-year return percentage ("-95.44%", "1317.18%") that landed in the
recommendation column when Finviz shifted view 141's columns; a 1-5 scale cannot be recovered from
it, and scoring it anyway is precisely the incident this table is still recovering from
(``scripts/quarantine_fabricated_analyst_ratings.py``). Whatever remains is not collectable at all:
since the 2026-09-13 header-keyed rewrite no configured Finviz view carries a "Recom" column, so
the enrichment has no recommendation to write. A backfill script that filled these rows would
manufacture data; this one refuses by construction — it has no write path to reach for.

WHAT IT DOES
------------
Reads (read-only session), classifies, and prints:

  * how many rows in the window are NULL, by cause;
  * the only class a backfill could legitimately repair (a clean 1-5 in ``recom_raw``) — expected
    to be zero, because the quarantine only touched rows whose score was OFF the 1-5 scale;
  * the exact UPDATE it would run for that class, as text, and never executes it.

EXIT
----
    0  the report was produced (findings are output, not failure)
    1  the database could not be read
    2  usage

MBI_BEHAVIOR = 0: no broker, no order, no send. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCHEMA = "AnalystRecomBackfillReport@v1"

#: A row's NULL recom_score, by why it is NULL.
CAUSE_PERCENT_VALUE = "percent_value_from_column_shift"  # recom_raw is a return %, from the 2026-09 column shift
CAUSE_OFF_SCALE = "off_scale_value"  # recom_raw is a number outside 1-5
CAUSE_NOT_COLLECTED = "no_value_collected"  # no recom was ever collected for the row
CAUSE_RECOVERABLE = "recoverable_from_raw"  # recom_raw is a clean 1-5: the only fillable class

CAUSES = (CAUSE_PERCENT_VALUE, CAUSE_OFF_SCALE, CAUSE_NOT_COLLECTED, CAUSE_RECOVERABLE)

#: The only rows a backfill could legitimately fill. Kept as SQL text for the report; never run.
WOULD_RUN_SQL = (
    "UPDATE analyst_consensus_history SET recom_score = recom_raw::numeric "
    "WHERE recom_score IS NULL AND recom_raw ~ '^[0-9]+(\\.[0-9]+)?$' "
    "AND recom_raw::numeric BETWEEN 1 AND 5"
)


def classify(recom_raw: str | None) -> str:
    """Why this row's recom_score is NULL. Pure — the whole diagnosis, testable without a database.

    ``recom_raw`` is the provider string the row kept (the quarantine never touched it).
    """
    raw = "" if recom_raw is None else str(recom_raw).strip()
    if not raw or raw == "-":
        return CAUSE_NOT_COLLECTED
    if "%" in raw:
        return CAUSE_PERCENT_VALUE
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return CAUSE_OFF_SCALE
    if 1.0 <= value <= 5.0:
        return CAUSE_RECOVERABLE
    return CAUSE_OFF_SCALE


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
        raise SystemExit(f"ERROR: database settings unavailable: {missing}. Refusing to guess.")
    return env


_READ_SQL = (
    "SELECT recom_raw FROM analyst_consensus_history"
    " WHERE recom_score IS NULL AND snapshot_date > current_date - %s::int"
)


def report(rows: list[str | None], days: int) -> dict:
    """Count the window's NULL rows by cause. Pure."""
    by_cause: dict[str, int] = {c: 0 for c in CAUSES}
    for raw in rows:
        by_cause[classify(raw)] += 1
    return {
        "schema": SCHEMA,
        "window_days": days,
        "null_rows": len(rows),
        "by_cause": by_cause,
        "recoverable": by_cause[CAUSE_RECOVERABLE],
        "would_run_sql": WOULD_RUN_SQL,
        "write_path": "none — this script has no --apply, by design",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Classify NULL recom_score rows by cause. Dry run only.")
    ap.add_argument("--days", type=int, default=90, help="window in days (default 90)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)
    if args.days <= 0:
        print("error: --days must be positive", file=sys.stderr)
        return 2

    try:
        import psycopg2
    except ImportError:
        print("error: psycopg2 is unavailable", file=sys.stderr)
        return 1

    env = _env_from_runtime()
    try:
        conn = psycopg2.connect(
            host=env["DB_HOST"],
            port=env.get("DB_PORT", 5432),
            dbname=env["DB_NAME"],
            user=env["DB_USER"],
            password=env["DB_PASSWORD"],
            # Read-only at the session level: there is no --apply, and this makes that a property
            # of the session rather than a promise in a docstring.
            options="-c default_transaction_read_only=on",
        )
    except Exception as exc:  # noqa: BLE001 -- any connection failure is "could not read"
        print(f"error: could not open a read-only session: {exc}", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute(_READ_SQL, (args.days,))
            rows = [r[0] for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001 -- any read failure is "could not read"; a partial report would be a guess
        print(f"error: could not read analyst_consensus_history: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.rollback()
        conn.close()

    out = report(rows, args.days)
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    print("analyst_consensus_history.recom_score — NULL rows by cause (DRY RUN, nothing written)")
    print("-" * 78)
    print(f"  window                 : last {args.days} days")
    print(f"  NULL recom_score rows  : {out['null_rows']:,}")
    for cause in CAUSES:
        print(f"    {cause:<32}: {out['by_cause'][cause]:,}")
    print(f"  recoverable from raw   : {out['recoverable']:,}")
    print("\n  A percent value is the 2026-09 column shift, not a rating; it cannot be scored.")
    print("  No collection exists for the rest (no configured Finviz view returns 'Recom').")
    print(f"\n  the only UPDATE a backfill could justify (NOT EXECUTED):\n    {WOULD_RUN_SQL}")
    print("\nDRY RUN — nothing written. This script has no --apply by design.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
