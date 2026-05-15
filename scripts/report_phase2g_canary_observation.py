#!/usr/bin/env python3
"""report_phase2g_canary_observation.py — Summarize Phase 2G hybrid canary behavior from logs and DB."""
import argparse, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2g-obs] {msg}", flush=True)

def parse_deep_window_log(since_hours=72):
    logfile = PROJ / "logs" / "deep_overnight_llm_window.log"
    if not logfile.exists():
        return {"status": "no_log", "runs": []}
    cutoff = datetime.now() - timedelta(hours=since_hours)
    lines = logfile.read_text().splitlines()
    runs = []
    current = None
    for line in lines:
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        if ts < cutoff:
            continue
        if "Deep Overnight LLM Window Starting" in line:
            current = {"start": str(ts), "hybrid": False, "prefetch": False, "jobs": 0}
        if current:
            if "Hybrid RAG" in line and "ENABLED" in line:
                current["hybrid"] = True
            if "STAGE A" in line or "prefetch" in line.lower():
                current["prefetch"] = True
            if "CACHED" in line:
                current["jobs"] = current.get("jobs", 0) + 1
            if "Deep Overnight LLM Window Complete" in line:
                current["end"] = str(ts)
                runs.append(current)
                current = None
    return {"status": "ok", "runs": runs, "total_runs": len(runs)}

def main():
    p = argparse.ArgumentParser(description="Phase 2G canary observation report")
    p.add_argument("--since", type=int, default=72, help="Hours to look back")
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    obs = parse_deep_window_log(args.since)
    hybrid_runs = [r for r in obs.get("runs", []) if r.get("hybrid")]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "since_hours": args.since,
        "total_deep_runs": obs.get("total_runs", 0),
        "hybrid_runs": len(hybrid_runs),
        "runs": hybrid_runs,
        "recommendation": "observe_after_next_scheduled_run" if not hybrid_runs else "canary_data_available",
    }

    log(f"Deep runs in last {args.since}h: {obs.get('total_runs', 0)}")
    log(f"Hybrid runs: {len(hybrid_runs)}")
    for r in hybrid_runs:
        log(f"  {r.get('start')} — jobs={r.get('jobs',0)} prefetch={r.get('prefetch')}")

    if not hybrid_runs:
        log("No hybrid deep runs observed yet. Will have data after next 23:00 UTC run.")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        lines = ["# Phase 2G Canary Observation Report", f"\n**Since:** last {args.since} hours",
                 f"\n## Summary\n", f"| Metric | Value |", f"|--------|-------|",
                 f"| Deep runs | {obs.get('total_runs', 0)} |",
                 f"| Hybrid runs | {len(hybrid_runs)} |",
                 f"| Recommendation | {report['recommendation']} |"]
        if hybrid_runs:
            lines.extend(["\n## Hybrid Runs\n"] + [f"- {r.get('start')}: {r.get('jobs',0)} jobs, prefetch={r.get('prefetch')}" for r in hybrid_runs])
        else:
            lines.append("\nNo hybrid runs observed. Data will be available after next scheduled run at 23:00 UTC.")
        lines.append("\n## Production Impact\n\nNone. Read-only observation.\n")
        Path(args.output_md).write_text("\n".join(lines))

if __name__ == "__main__":
    main()
