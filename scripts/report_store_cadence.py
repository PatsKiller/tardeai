#!/usr/bin/env python3
"""C5 — declared cadence versus observed output, for stores feeding operator surfaces.

strategy_signals stopped advancing on 2026-08-07 and nothing watched the date. Three
detectors reported nothing for 24 days. This compares each declared store's expected
cadence against the actual age of its durable artifact.

THIS IS AN EXTENSION, NOT A SECOND MONITOR. Every verdict comes from
scripts/lib/lane_registry.evaluate_lane -- the same evaluator, the same five
verdicts, the same scheduler discovery. AGENTS.md §13.5 exists because a parallel
monitor is how two answers to one question get built. The only thing new here is the
data file, and it is separate from config/lane_registry.json solely because that file
is owned by another agent during this run; the two are meant to merge.

    python3 scripts/report_store_cadence.py --json
    python3 scripts/report_store_cadence.py            # human summary

Read-only. Never writes. Exit 0 always unless --strict is given.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "Operator-facing cadence report. The schedule is PROPOSED, not installed -- "
    "cron and systemd are operator-only, so this contract has no scheduled caller "
    "by design and not by omission. Surfacing a SILENT verdict to an operator "
    "surface is named remaining work: a finding that appears only in a log file is "
    "the defect this package exists to correct. Invoked today by the operator CLI "
    "and by tests/test_store_cadence.py."
)

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import lane_registry as LR  # noqa: E402

STORES = ROOT / "config" / "operator_surface_stores.json"


def _db_query(sql: str):
    """Real DB access, or None so the verdict is UNVERIFIABLE rather than SILENT.

    Conflating "cannot read the signal" with "the lane is silent" is how a monitor
    starts lying; lane_registry is explicit about that and this preserves it.
    """
    try:
        from db_adapter import get_connection
        cur = get_connection().cursor()
        cur.execute(sql)
        return cur.fetchall()
    except Exception:
        return None


def evaluate(path: Path = STORES, *, db_query=None, found=None, now=None) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("lanes") or []
    found = found if found is not None else LR.discover_all()
    q = db_query if db_query is not None else _db_query
    results = [
        LR.evaluate_lane(r, found=found, root=ROOT, db_query=q, now=now) for r in rows
    ]
    for res, row in zip(results, rows):
        res["surface"] = row.get("surface")
        res["note"] = row.get("note")
    findings = [r for r in results if not r["ok"]]
    return {
        "schema": "StoreCadence@v1",
        "authority": LR.AUTHORITY,
        "stores": len(results),
        "findings": len(findings),
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any store is a finding (SILENT/ORPHANED)")
    args = ap.parse_args()

    out = evaluate()
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"stores={out['stores']}  findings={out['findings']}")
        for r in out["results"]:
            age = r["output_age_hours"]
            print("  %-30s %-15s age=%-9s cadence=%-5s  %s"
                  % (r["lane_id"], r["verdict"],
                     f"{age}h" if age is not None else "-",
                     r["expected_cadence_hours"], r["surface"] or ""))
    return 1 if (args.strict and out["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
