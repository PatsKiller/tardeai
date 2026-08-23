#!/usr/bin/env python3
"""Seed the ticker-first graph from the complete tracked coverage universe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()
    root = Path(args.root)
    from scripts.lib.symbol_thesis_coverage import build_coverage_report
    from scripts.lib.ticker_knowledge_graph import seed_profiles
    report = build_coverage_report(root=root, material_only=False)
    result = seed_profiles(root, report.get("rows") or [])
    result["coverage_rows"] = len(report.get("rows") or [])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
