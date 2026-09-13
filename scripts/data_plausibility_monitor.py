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

# psycopg2 is imported lazily inside main(), NOT here. The rules in this module
# -- _violation_predicate, _check_single_scale, _alert -- are pure and are tested
# without a database. A module-level driver import made those tests uncollectable
# anywhere psycopg2 is absent, which is every CI runner: the file errored at
# import and the gate went red without running a single assertion. Locally it
# passed, because the venv has the driver.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_PATH = PROJECT_ROOT / "config" / "data_plausibility_contracts.json"

SCHEMA = "DataPlausibilityReport@v1"
RECEIPT_NAME = "data_plausibility_last_run.json"

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


STATE_PATH = Path.home() / ".local/state/tradeai/data_plausibility_last_alert.json"


def _alert(results: list[dict], blocking: list[dict]) -> None:
    """Tell the operator, but only when the picture actually changed.

    An alert that fires every run for a known-open violation trains the reader to
    ignore it, and an ignored alert is worse than none -- it looks like coverage
    while providing none. So the fingerprint is the set of violating columns and
    their counts: a new violation, a resolved one, or a materially changed count
    speaks; a steady state stays quiet.
    """
    fingerprint = {f"{r['table']}.{r['column']}": r["violations"] for r in blocking}

    previous = {}
    try:
        previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    except (OSError, ValueError):
        pass

    if fingerprint == previous:
        print("\n  alert: suppressed — identical to the last run (same columns, same counts).")
        return

    if not fingerprint:
        body = (
            "[DATA_INTEGRITY] ✅ Data plausibility: all declared columns now satisfy their "
            "contracts.\n\nPreviously violating: " + ", ".join(previous)
            if previous
            else "[DATA_INTEGRITY] ✅ Data plausibility: all declared columns satisfy their contracts."
        )
    else:
        # A column that starts violating is a live integrity breach and earns an
        # interrupt; a known-open one already reported does not, or the alarm
        # becomes wallpaper. telegram_alert_router routes on "CRITICAL", so the
        # word is load-bearing -- it is the escalation, not decoration. Only a
        # NEWLY violating column gets it.
        newly = [k for k in fingerprint if k not in previous]
        lines = [
            # See the note in check_expected_services._alert: the sentinel, not
            # the wording, is what routes this immediately.
            (
                "[DATA_INTEGRITY] 🚨 A new column is off its declared scale"
                if newly
                else "[DATA_INTEGRITY] 🚨 Data plausibility — declared scale violated"
            ),
            "",
            "A value off its declared scale is not a rounding problem. The Finviz",
            'column shift published stocks down -100% as "Strong Buy" for five',
            "months because nothing measured this.",
            "",
        ]
        for r in sorted(blocking, key=lambda x: -x["violations"]):
            pct = (100.0 * r["violations"] / r["total"]) if r["total"] else 0.0
            lines.append(f"• {r['table']}.{r['column']}")
            lines.append(f"    {r['violations']:,} of {r['total']:,} rows ({pct:.1f}%) — {r['detail']}")
        if newly:
            lines += ["", "NEW since the last run: " + ", ".join(newly)]
        resolved = [k for k in previous if k not in fingerprint]
        if resolved:
            lines += ["", "Resolved since last run: " + ", ".join(resolved)]
        lines += [
            "",
            "Either the data is wrong or the contract is wrong.",
            "config/data_plausibility_contracts.json carries the reasoning.",
        ]
        body = "\n".join(lines)

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from telegram_alert import send_telegram

        ok = send_telegram(body, message_class="operator_alert")
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform")
    except Exception as exc:
        # An alerting failure must never mask the finding it was carrying.
        print(f"\n  alert: FAILED to send ({exc}). The findings above still stand.", file=sys.stderr)
        return

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"fingerprint": fingerprint}, indent=2))
    except OSError as exc:
        print(f"  alert: could not record state ({exc}); next run may repeat.", file=sys.stderr)


def _write_run_receipt(checked: int, off: int, detail: dict) -> None:
    """Prove this ran, every run, whether or not it found anything.

    The alert state file only changes when findings change, so a quiet run
    leaves no trace -- and a timer that silently stopped would look exactly like
    a clean result. config/lane_registry.json requires an output_signal that is
    a durable artifact, "not its exit code, not its log file existing", and this
    is that artifact.
    """
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ran_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "checked": checked,
                    "off": off,
                    **detail,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the violation set changes")
    args = ap.parse_args()

    if not CONTRACTS_PATH.exists():
        print(f"ERROR: no contracts at {CONTRACTS_PATH}", file=sys.stderr)
        return 2
    contracts = json.loads(CONTRACTS_PATH.read_text())["contracts"]

    env = _db_env()
    if not env.get("DB_NAME"):
        print("ERROR: database settings unavailable", file=sys.stderr)
        return 2

    try:
        import psycopg2  # noqa: PLC0415 — see the note beside the imports
    except ImportError:
        print("ERROR: psycopg2 is not installed; cannot measure the database.", file=sys.stderr)
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
        if args.alert:
            _alert(results, blocking)
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

    _write_run_receipt(
        len(results), len(blocking), {"blocking_items": [f"{r['table']}.{r['column']}" for r in blocking]}
    )

    if args.alert:
        _alert(results, blocking)

    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
