#!/usr/bin/env python3
"""generate_analyst_weekly_review.py — automated Weekly Portfolio Review (DOCX/PDF).

Thin wrapper around analyst_report_builder.build_weekly_review() + report_export.
Cron: Sunday 21:00 (same slot as generate_weekly_docx.py).

Usage:
    .venv/bin/python scripts/generate_analyst_weekly_review.py
    .venv/bin/python scripts/generate_analyst_weekly_review.py --format pdf
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from analyst_report_builder import build_weekly_review, save_report_json
from report_export import export_report


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Weekly Portfolio Review")
    ap.add_argument("--format", default="docx", choices=("docx", "pdf", "all"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    report = build_weekly_review()
    stem = f"weekly_review_{date.today().strftime('%Y%m%d')}"
    save_report_json(report, stem=stem)

    if args.dry_run:
        import json
        print(json.dumps(report.get("meta", {}), indent=2))
        return 0

    formats = ["docx", "pdf"] if args.format == "all" else [args.format]
    for fmt in formats:
        result = export_report(report, fmt, output_stem=stem)
        if result.get("ok"):
            print(f"[weekly] {fmt.upper()}: {result.get('url')} ({result.get('size_kb')} KB)")
        else:
            print(f"[weekly] {fmt.upper()} failed: {result.get('error')}", file=sys.stderr)
            if fmt == "docx":
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())