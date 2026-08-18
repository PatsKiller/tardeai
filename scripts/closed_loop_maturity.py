#!/usr/bin/env python3
"""Maturity-closure operators: queue-health, recon persist, circuit, need-decision.

READ_ONLY_ADVISORY. Default dry-run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("queue-health", "reconcile", "circuit", "need"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--symbol", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "queue-health":
        from lib.hermes_queue_health import build
        out = build()
    elif args.cmd == "reconcile":
        from lib.cio_reconciliation import build, persist
        out = persist() if args.apply else build()
    elif args.cmd == "circuit":
        from lib.research_circuit import load
        out = load()
    else:
        from lib.research_need_decision import decide
        out = decide({"symbol": args.symbol, "held": True})
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
