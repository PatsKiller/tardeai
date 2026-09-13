#!/usr/bin/env python3
"""Measure declared numeric columns against their declared scale. Read-only.

WHY
---
For five months `analyst_consensus_history.recom_score` held ten-year return
percentages on a column declared as a 1-5 analyst scale, and the labels derived
from it were ANTI-correlated with reality: stocks down -100% published as
"Strong Buy". Nothing failed. Every value parsed, every type converted, every row
stored. 97.9% of the table was wrong and no gate anywhere noticed, because the
column's scale existed only in a docstring.

This monitor is the gate that was missing. It reads
config/data_plausibility_contracts.json, measures each declared column, and
reports what violates its contract.

It NEVER writes to the tables it inspects -- it opens a read-only session.

A violation is not automatically a defect: it may equally mean the contract is
wrong. Both are worth knowing, and both are invisible today.

USAGE
-----
    python scripts/data_plausibility_monitor.py           # human-readable
    python scripts/data_plausibility_monitor.py --json    # machine-readable

EXIT CODES
----------
    0  no BLOCK violations (WARN may be present)
    1  at least one BLOCK violation
    2  could not run (no contracts, no database)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_PATH = PROJECT_ROOT / "config" / "data_plausibility_contracts.json"

SCHEMA = "DataPlausibilityReport@v1"

NO_CONSUMER_REASON = (
    "this IS a data-integrity gate; an operator or a scheduled run invokes it and "
    "reads the report, nothing imports it. Same shape as check_test_coverage.py "
    "and check_dark_contracts.py."
)


def _db_env() -> dict:
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
    return env


def _violation_predicate(contract: dict) -> str:
    """SQL that is TRUE for a row violating the contract.

    NULL is never a violation: absent data is a different problem from wrong
    data, and conflating them is how "no rating" became "Strong Buy".
    """
    col = f'"{contract["column"]}"'
    rule = contract["rule"]

    if rule == "range":
        return f"{col} IS NOT NULL AND NOT ({col} BETWEEN {contract['min']} AND {contract['max']})"
    if rule == "min":
        return f"{col} IS NOT NULL AND {col} < {contract['min']}"
    if rule == "max":
        return f"{col} IS NOT NULL AND {col} > {contract['max']}"
    if rule == "finite":
        # NaN is not comparable, so test it by text. 'NaN'::float = 'NaN'::float
        # is false, which is exactly why these rows survive ordinary range checks.
        return f"{col} IS NOT NULL AND {col}::text IN ('NaN','nan','Infinity','-Infinity')"
    if rule == "single_scale":
        # Cannot be expressed per-row: it is a property of the population.
        return ""
    raise ValueError(f"unknown rule {rule!r}")


def _check_single_scale(cur, contract: dict) -> dict:
    """A column must pick one scale. Both populations present == violation."""
    table, col = contract["table"], f'"{contract["column"]}"'
    cur.execute(
        f"SELECT count(*) FILTER (WHERE {col} > 0 AND {col} <= 1),"
        f"       count(*) FILTER (WHERE {col} > 1),"
        f"       count(*) FILTER (WHERE {col} IS NOT NULL)"
        f"  FROM {table}"
    )
    unit, hundred, total = cur.fetchone()
    violating = min(unit, hundred)  # the smaller population is the anomaly
    return {
        "violations": violating if (unit and hundred) else 0,
        "total": total,
        "detail": f"{unit:,} rows in (0,1] and {hundred:,} rows >1",
        "samples": [],
    }


def _check(cur, contract: dict) -> dict | None:
    table = contract["table"]
    column = contract["column"]

    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table, column),
    )
    if not cur.fetchone():
        return {
            "table": table,
            "column": column,
            "severity": "WARN",
            "violations": 0,
            "total": 0,
            "status": "COLUMN_ABSENT",
            "detail": "declared in contracts but not present in the database",
            "samples": [],
        }

    if contract["rule"] == "single_scale":
        result = _check_single_scale(cur, contract)
    else:
        pred = _violation_predicate(contract)
        cur.execute(f"SELECT count(*) FROM {table} WHERE {pred}")
        violations = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {table}")
        total = cur.fetchone()[0]
        samples = []
        if violations:
            cur.execute(f'SELECT "{column}"::text FROM {table} WHERE {pred} LIMIT 3')
            samples = [r[0] for r in cur.fetchall()]
        result = {
            "violations": violations,
            "total": total,
            "detail": f"rule={contract['rule']}",
            "samples": samples,
        }

    return {
        "table": table,
        "column": column,
        "severity": contract["severity"],
        "status": "VIOLATION" if result["violations"] else "OK",
        **result,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    if not CONTRACTS_PATH.exists():
        print(f"ERROR: no contracts at {CONTRACTS_PATH}", file=sys.stderr)
        return 2
    contracts = json.loads(CONTRACTS_PATH.read_text())["contracts"]

    env = _db_env()
    if not env.get("DB_NAME"):
        print("ERROR: database settings unavailable", file=sys.stderr)
        return 2

    conn = psycopg2.connect(
        host=env["DB_HOST"],
        port=env.get("DB_PORT", 5432),
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
    )
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()

    results = []
    for contract in contracts:
        try:
            results.append(_check(cur, contract))
        except Exception as exc:  # a broken contract must not hide the others
            results.append(
                {
                    "table": contract["table"],
                    "column": contract["column"],
                    "severity": "WARN",
                    "status": "CHECK_FAILED",
                    "violations": 0,
                    "total": 0,
                    "detail": str(exc)[:160],
                    "samples": [],
                }
            )
    cur.close()
    conn.close()

    blocking = [r for r in results if r["status"] == "VIOLATION" and r["severity"] == "BLOCK"]

    if args.json:
        print(
            json.dumps(
                {
                    "schema": "DataPlausibilityReport@v1",
                    "checked": len(results),
                    "violations": sum(1 for r in results if r["status"] == "VIOLATION"),
                    "blocking": len(blocking),
                    "results": results,
                },
                indent=2,
                default=str,
            )
        )
        return 1 if blocking else 0

    print("Data plausibility — declared columns measured against declared scale")
    print("=" * 78)
    for r in sorted(results, key=lambda x: (x["status"] != "VIOLATION", x["table"])):
        mark = "OK   " if r["status"] == "OK" else f"{r['severity']:<5}"
        pct = (100.0 * r["violations"] / r["total"]) if r["total"] else 0.0
        print(f"  [{mark}] {r['table']}.{r['column']}")
        if r["status"] == "VIOLATION":
            print(f"           {r['violations']:,} of {r['total']:,} rows ({pct:.1f}%) — {r['detail']}")
            if r["samples"]:
                print(f"           samples: {r['samples']}")
        elif r["status"] != "OK":
            print(f"           {r['status']}: {r['detail']}")
    print("-" * 78)
    print(
        f"  checked={len(results)}  violations="
        f"{sum(1 for r in results if r['status'] == 'VIOLATION')}  blocking={len(blocking)}"
    )
    if blocking:
        print("\n  A BLOCK violation means the value cannot be valid on its declared")
        print("  scale. Either the data is wrong or the contract is wrong; both are")
        print("  worth a look, and neither is visible without this check.")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
