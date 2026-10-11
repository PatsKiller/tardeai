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



def _execute() -> int:
    ap = argparse.ArgumentParser(description="Generate Daily Intelligence Digest document")
    ap.add_argument("--days", type=int, default=1, help="lookback days for portal actions")
    ap.add_argument("--format", default="docx", choices=("docx", "pdf", "json", "all"))
    ap.add_argument("--dry-run", action="store_true", help="build JSON only, no export")
    args = ap.parse_args()

    from analyst_report_builder import build_daily_digest, save_report_json
    from report_export import export_report
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


def main(argv=None) -> int:
    """Strict offline inspection before the legacy business execution path."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="Generate Daily Intelligence Digest document", allow_abbrev=False)
    ap.add_argument("--days", type=int, default=1, help="lookback days for portal actions")
    ap.add_argument("--format", default="docx", choices=("docx", "pdf", "json", "all"))
    ap.add_argument("--dry-run", action="store_true", help="build JSON only, no export")
    ap.add_argument("--receipt", type=Path, help="legacy scheduled receipt override")
    args = ap.parse_args(argv)
    lane = "generate-analyst-daily-digest"
    if args.dry_run:
        print(f"DRY-RUN {lane}: would build daily digest and export requested formats; no JSON/chart/export, DB or network; options={vars(args)}; inputs NOT_MEASURED")
        return 0
    try:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        from lib.scheduled_job_receipt import run_with_receipt
        result = run_with_receipt(_execute, script="generate_analyst_daily_digest", root=PROJECT_ROOT)
        rc = int(result) if isinstance(result, int) else 0
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="generate_analyst_daily_digest.py", summary={"completed": rc == 0})
        raise
    except Exception as exc:
        write_lane_receipt(lane, ok=False, exit_code=1, started_at=started, script="generate_analyst_daily_digest.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="generate_analyst_daily_digest.py", summary={"completed": rc == 0})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
