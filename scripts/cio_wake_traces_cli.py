#!/usr/bin/env python3
"""CLI: list CIO wake traces (P5). Zero LLM.

Usage:
  python scripts/cio_wake_traces_cli.py
  python scripts/cio_wake_traces_cli.py --limit 20 --llm blocked_cap
  python scripts/cio_wake_traces_cli.py --plan plan_abc --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="List CIO wake traces (READ_ONLY)")
    ap.add_argument("--limit", "-n", type=int, default=15)
    ap.add_argument("--llm", default=None, help="Filter llm= e.g. blocked_cap")
    ap.add_argument("--plan", default=None, dest="plan_id")
    ap.add_argument("--wake", default=None, dest="wake_id")
    ap.add_argument("--source", default=None)
    ap.add_argument("--path", default=None, help="Override JSONL path")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        from scripts.lib.cio_wake_traces import format_traces, list_traces
    except Exception:
        from lib.cio_wake_traces import format_traces, list_traces  # type: ignore

    rows = list_traces(
        limit=args.limit,
        plan_id=args.plan_id,
        llm=args.llm,
        wake_id=args.wake_id,
        source=args.source,
        path=args.path,
    )
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print(format_traces(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
