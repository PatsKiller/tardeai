#!/usr/bin/env python3
"""report_phase3_media_prose_usage.py — Summarize Phase 3 media/prose routing usage."""
import argparse, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase3-usage] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since-hours", type=int, default=72)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logfile = PROJ / "logs" / "phase3_media_prose_routing.log"
    pilot_file = PROJ / "docs" / "llm_fleet" / "phase3_media_prose" / "v4_1_phase3c_routing_pilot_results.json"

    calls = []
    if logfile.exists():
        for line in logfile.read_text().splitlines():
            if "phase3-router" in line or "phase3_media" in line:
                calls.append(line)

    pilot_data = {}
    if pilot_file.exists():
        pilot_data = json.loads(pilot_file.read_text())

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "since_hours": args.since_hours,
        "log_calls": len(calls),
        "pilot_available": bool(pilot_data),
        "pilot_count": pilot_data.get("aggregate", {}).get("total", 0) if pilot_data else 0,
        "recommendation": "observe_after_more_usage" if len(calls) < 10 else "sufficient_data",
    }

    if args.verbose:
        log(f"Log calls found: {len(calls)}")
        log(f"Pilot data: {'available' if pilot_data else 'none'}")
        if len(calls) < 10:
            log("Insufficient live usage data. Using pilot results as baseline.")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).write_text(
            f"# Phase 3D Usage Report\n\n**Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Log calls: {len(calls)}\nPilot data: {'yes' if pilot_data else 'no'}\n"
            f"Recommendation: {report['recommendation']}\n\nNote: Phase 3C routing was just enabled. "
            f"More usage data will accumulate as content workflows use the router.\n")

if __name__ == "__main__":
    main()
