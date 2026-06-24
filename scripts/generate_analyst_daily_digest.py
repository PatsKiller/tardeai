#!/usr/bin/env python3
"""generate_analyst_daily_digest.py — automated Daily Intelligence Digest (DOCX/PDF).

Builds analyst-grade daily digest via analyst_report_builder and exports to
data/portfolios/reports/analyst/. Designed for cron after morning intelligence runs.

Usage:
    .venv/bin/python scripts/generate_analyst_daily_digest.py
    .venv/bin/python scripts/generate_analyst_daily_digest.py --format pdf
    .venv/bin/python scripts/generate_analyst_daily_digest.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from analyst_report_builder import build_daily_digest, save_report_json
from report_export import export_report


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Daily Intelligence Digest document")
    ap.add_argument("--days", type=int, default=1, help="lookback days for portal actions")
    ap.add_argument("--format", default="docx", choices=("docx", "pdf", "json", "all"))
    ap.add_argument("--dry-run", action="store_true", help="build JSON only, no export")
    args = ap.parse_args()

    report = build_daily_digest(days=args.days)
    ts = datetime.now().strftime("%Y%m%d")
    stem = f"daily_digest_{ts}"

    json_path = save_report_json(report, stem=stem)
    print(f"[digest] JSON saved: {json_path}")

    if args.dry_run:
        print(json.dumps(report.get("meta", {}), indent=2))
        return 0

    formats = ["docx", "pdf"] if args.format == "all" else [args.format]
    for fmt in formats:
        result = export_report(report, fmt, output_stem=stem)
        if result.get("ok"):
            print(f"[digest] {fmt.upper()} export: {result.get('url')} ({result.get('size_kb')} KB)")
        else:
            print(f"[digest] {fmt.upper()} export failed: {result.get('error')}", file=sys.stderr)
            if fmt == "pdf":
                continue
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())