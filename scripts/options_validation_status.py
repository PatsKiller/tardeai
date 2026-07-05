#!/usr/bin/env python3
"""options_validation_status.py — advisory validation-gate report (Stage B).

Prints per-strategy paper-validation progress (n/30 outcomes, profit factor,
win rate, calendar months) against the strategy YAML's validation_gate.

ADVISORY ONLY: this tool reports "gate not met" or "gate met — operator
decision required". It never enables anything; live_allowed stays false in
config and there is no write path here beyond the optional --sync-registry
advisory blob (trades_taken + metadata.paper_validation on strategy_registry).

Usage:
    .venv/bin/python scripts/options_validation_status.py [--json]
    .venv/bin/python scripts/options_validation_status.py --strategy deep_itm_call --json
    .venv/bin/python scripts/options_validation_status.py --sync-registry
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

from lib.options_pipeline.validation import (  # noqa: E402
    SUPPORTED_STRATEGIES,
    update_registry_maturity,
    validation_status,
)


def _print_human(report: dict) -> None:
    m = report["metrics"]
    print(f"[{report['strategy_id']}] {report['display_name']} "
          f"— {report['lifecycle_status']} · paper_only={report['paper_only']} "
          f"· live_allowed={report['execution'].get('live_allowed')}")
    print(f"  {report['progress_label']} · wins {m['wins']} / losses {m['losses']} "
          f"/ scratches {m['scratches']} · net P/L ${m['net_pnl']:,.2f}")
    wr = f"{m['win_rate']:.2%}" if m["win_rate"] is not None else "—"
    pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else "—"
    print(f"  win rate {wr} · profit factor {pf} · {m['calendar_months']} months")
    for c in report["checks"]:
        print(f"    [{'PASS' if c['pass'] else 'fail'}] {c['id']}: "
              f"{c['actual'] if c['actual'] is not None else '—'} "
              f"(required {c['required']})")
    print(f"  VERDICT: {report['message']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Paper-strategy validation gate report (advisory)")
    ap.add_argument("--strategy", default="", help="one strategy (default: all supported)")
    ap.add_argument("--json", action="store_true", help="emit full JSON")
    ap.add_argument("--sync-registry", action="store_true",
                    help="also mirror the advisory blob onto strategy_registry "
                         "(trades_taken + metadata.paper_validation only)")
    args = ap.parse_args(argv)

    strategies = [args.strategy] if args.strategy else list(SUPPORTED_STRATEGIES)
    reports = []
    rc = 0
    for sid in strategies:
        report = validation_status(sid)
        if report.get("ok") and args.sync_registry:
            report["registry_sync"] = update_registry_maturity(sid, status_report=report)
        reports.append(report)
        if not report.get("ok"):
            rc = 1

    if args.json:
        print(json.dumps({"strategies": reports}, indent=2, default=str))
    else:
        for r in reports:
            if r.get("ok"):
                _print_human(r)
            else:
                print(f"ERROR: {r.get('error')}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
