#!/usr/bin/env python3
"""Daily deterministic integrity sweep.

    python3 scripts/run_integrity_checks.py            # human readable
    python3 scripts/run_integrity_checks.py --json     # machine readable
    python3 scripts/run_integrity_checks.py --alert    # + Telegram on P0/P1

Reports; does not repair. See lib/deterministic_integrity for why — the obvious
fix for one of these findings would have destroyed a 32,060-row corpus.

Exit code is 0 whenever the CHECK RAN. Findings live in the JSON, not the exit
status, so systemd cannot confuse "the sweep crashed" with "the sweep found
something" — the distinction that let a broken alarm read as healthy for 24 days.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: Producers whose absence has already cost real time. Each earned its place by
#: being found unscheduled while everything downstream reported success.
PRODUCERS = (
    "mint_identity_registry.py",       # the GUID spine
    "build_catalyst_graph.py",         # unscheduled; graph frozen (2026-09-06)
    "strategy_rule_engine.py",         # unscheduled; emptied the CIO join (30d)
    "db_retention.py",                 # retention that never runs is not a policy
)

#: Crons known to have been disabled during an incident and never restored.
WATCH_CRONS = (
    "taxonomy_tagger.py",              # commented 2026-07-02, sector tagging 5%
    "mint_identity_registry.py",
)

#: (consumer, table it INNER JOINs). An empty producer here is silent forever.
JOIN_PAIRS = (
    ("cio_decision_engine", "strategy_rule_evaluations"),
    ("cio_decision_engine", "ticker_strategy_classifications"),
)


def _owner_map():
    """Every pipeline declares `output_tables`; until now exactly one place read
    that field, and only to forward it to a display payload. This is what makes
    the declaration load-bearing instead of decorative."""
    try:
        import pipeline_stage_owner_map as M
        for v in vars(M).values():
            if isinstance(v, dict) and any(
                    isinstance(x, dict) and "output_tables" in x for x in v.values()):
                return v
    except Exception as exc:
        print(f"[integrity] owner map unavailable ({type(exc).__name__})", file=sys.stderr)
    return {}


def _conn():
    try:
        import psycopg2
        from lib.env_bootstrap import load_env
        load_env()
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"))
    except Exception as exc:
        print(f"[integrity] no DB ({type(exc).__name__}) — source checks only",
              file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="Telegram on P0/P1")
    args = ap.parse_args()

    from lib.deterministic_integrity import run_all

    conn = _conn()
    try:
        report = run_all(conn=conn, producers=PRODUCERS,
                         watch_crons=WATCH_CRONS, join_pairs=JOIN_PAIRS,
                         owner_map=_owner_map())
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        c = report["counts"]
        print(f"[integrity] {report['as_of']}  P0={c['P0']} P1={c['P1']} P2={c['P2']}")
        for f in report["findings"]:
            print(f"  [{f['severity']}] {f['check']}: {f['subject']}")
            print(f"        {f['detail']}")
            print(f"        fix: {f['remediation']}")
        if not report["findings"]:
            print("  no findings")

    if args.alert and (report["counts"]["P0"] or report["counts"]["P1"]):
        lines = [f"\U0001f6e0 Deterministic integrity — "
                 f"P0={report['counts']['P0']} P1={report['counts']['P1']}", ""]
        for f in report["findings"]:
            if f["severity"] in ("P0", "P1"):
                lines.append(f"[{f['severity']}] {f['check']}: {f['subject']}")
                lines.append(f"   {f['detail']}")
        lines.append("")
        lines.append("Reports only — nothing was repaired. Each line names its fix.")
        try:
            from telegram_alert import send_telegram
            send_telegram("\n".join(lines)[:3500])
        except Exception as exc:
            print(f"[integrity] telegram failed: {type(exc).__name__}", file=sys.stderr)
            return 2

    # 0 = the CHECK ran. Findings are in the report, not the exit code.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
