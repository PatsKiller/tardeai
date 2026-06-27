#!/usr/bin/env python3
"""Backfill MFE/MAE + profit-capture for TradeInView exit intelligence."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv/bin/python3"


def main():
    (ROOT / "state").mkdir(parents=True, exist_ok=True)
    steps = [
        [str(PY), str(ROOT / "scripts/trade_execution_analyzer.py"), "--mfe"],
        [str(PY), str(ROOT / "scripts/analyze_profit_capture_all_trades.py"), "--apply",
         "--json", str(ROOT / "state/trade_in_view_profit_capture.json"),
         "--markdown", str(ROOT / "docs/trade_in_view_profit_capture.md")],
    ]
    for cmd in steps:
        print("→", " ".join(cmd))
        r = subprocess.run(cmd, cwd=str(ROOT))
        if r.returncode != 0:
            print(f"WARNING: exit {r.returncode}", file=sys.stderr)
    print("Done.")


if __name__ == "__main__":
    main()