#!/usr/bin/env python3
"""options_paper_position_monitor.py — PR1 lifecycle monitor CLI (advisory only).

Mark-to-market open options positions via Schwab chain quotes; persist snapshots
and advisory labels. Optionally reconciles Alpaca paper fills first.

Usage:
    .venv/bin/python scripts/options_paper_position_monitor.py --run
    .venv/bin/python scripts/options_paper_position_monitor.py --run --dry-run
    .venv/bin/python scripts/options_paper_position_monitor.py --run --position-id 42
    .venv/bin/python scripts/options_paper_position_monitor.py --run --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Options position lifecycle monitor — advisory only, no order submit")
    parser.add_argument("--run", action="store_true",
                        help="monitor open positions (default action if no flags)")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute advisory labels only — no DB writes")
    parser.add_argument("--position-id", type=int, default=None,
                        help="monitor a single position by id")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON report (default when --run)")
    args = parser.parse_args(argv)

    if not args.run:
        parser.print_help()
        print("\nREFUSED: use --run to start the monitor")
        return 2

    _load_env()
    from lib.options_pipeline.paper_position_monitor import run_monitor

    report = run_monitor(position_id=args.position_id, dry_run=args.dry_run)
    if args.json or args.run:
        _print(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())