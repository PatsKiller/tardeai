#!/usr/bin/env python3
"""CLI: print coverage / gaps (read-only)."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"scripts"))
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
    ap.add_argument("--symbol")
    ap.add_argument("--gaps", action="store_true")
    ap.add_argument("--json", action="store_true")
    a=ap.parse_args()
    from scripts.lib.symbol_thesis_coverage import build_coverage_report, research_gap_triggers
    rep=build_coverage_report(root=Path(a.root))
    if a.symbol:
        row=next((r for r in rep["rows"] if r["symbol"]==a.symbol.upper()), None)
        print(json.dumps(row, indent=2))
        return 0
    if a.gaps:
        print(json.dumps(research_gap_triggers(rep)[:50], indent=2))
        return 0
    print(json.dumps({"counts": rep["coverage_counts"], "universe": rep["universe_counts"]}, indent=2))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
