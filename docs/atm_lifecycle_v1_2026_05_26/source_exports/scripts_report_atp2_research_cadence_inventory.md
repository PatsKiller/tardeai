# Source Export: scripts/report_atp2_research_cadence_inventory.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_atp2_research_cadence_inventory.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `7afe4dca743d534dcc1f166525257dc2e96d307735f4e419171f64acec048ac0` |
| **File Size** | 12831 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""
report_atp2_research_cadence_inventory.py
ATP-2 Research Cadence Inventory Report

Reads the crontab, classifies each job by category and session window,
and reports which ATP-2 cadence slots are covered vs missing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn

# ── Category classification ────────────────────────────────────────────────

CATEGORY_PATTERNS: dict[str, list[str]] = {
    "screener":               ["screener", "scan_universe", "trade_ai_scan", "run_screener"],
    "enrichment":             ["enrich", "finviz", "yahoo_analyst", "ticker_snapshot", "analyst_consensus"],
    "incubator":              ["incubator", "incubat"],
    "watchpool":              ["watchpool", "watch_pool", "watchlist"],
    "quote_refresh":          ["quote_refresh", "quote_update", "price_refresh", "live_quote"],
    "strategy_fit":           ["strategy_fit", "strategy_match", "universe_strategy"],
    "route_audit":            ["route_audit", "route_check", "route_verify"],
    "catalyst_news":          ["catalyst", "news_", "article_", "rss_", "sentiment"],
    "technical":              ["technical", "chart_", "ta_scan", "indicator"],
    "morning_packet":         ["morning_brief", "morning_packet", "daily_brief", "aegis_morning"],
    "proposal_revalidation":  ["revalidat", "proposal_check", "proposal_lifecycle"],
    "digest":                 ["digest", "summary_report", "daily_report", "weekly_report"],
    "agent":                  ["aegis", "agent_", "maria_", "steph_", "iris_"],
    "governance":             ["governance", "calibration", "reliability", "audit_log"],
    "system":                 ["backup", "vacuum", "cleanup", "maintenance", "health_check"],
}

SESSION_WINDOWS: dict[str, tuple[int, int]] = {
    "after_close":  (16, 18),
    "evening":      (17, 20),
    "overnight":    (20, 5),
    "premarket":    (5, 8),
    "market_open":  (8, 10),
    "market_hours": (10, 16),
}

ATP2_CADENCE_SLOTS = [
    "eod",
    "evening",
    "overnight",
    "premarket_4am",
    "premarket_7am",
    "premarket_9am",
    "proposal_revalidation_30min",
]

# Map ATP-2 slots to expected category + session combos
ATP2_SLOT_SIGNATURES: dict[str, dict] = {
    "eod":                          {"categories": ["screener", "enrichment", "digest"], "sessions": ["after_close"]},
    "evening":                      {"categories": ["enrichment", "catalyst_news", "strategy_fit"], "sessions": ["evening"]},
    "overnight":                    {"categories": ["agent", "catalyst_news", "technical"], "sessions": ["overnight"]},
    "premarket_4am":                {"categories": ["screener", "quote_refresh"], "sessions": ["premarket"]},
    "premarket_7am":                {"categories": ["strategy_fit", "enrichment"], "sessions": ["premarket"]},
    "premarket_9am":                {"categories": ["quote_refresh", "proposal_revalidation"], "sessions": ["premarket", "market_open"]},
    "proposal_revalidation_30min":  {"categories": ["proposal_revalidation"], "sessions": ["market_hours", "premarket", "market_open"]},
}


def classify_category(script_name: str) -> str:
    """Classify a script name into an ATP-2 category."""
    lower = script_name.lower()
    for cat, patterns in CATEGORY_PATTERNS.items():
        for pat in patterns:
            if pat in lower:
                return cat
    return "other"


def classify_session(hour: int | None, minute: int | None) -> str:
    """Classify a cron hour into a session window."""
    if hour is None:
        return "unknown"
    for session, (start, end) in SESSION_WINDOWS.items():
        if start < end:
            if start <= hour < end:
                return session
        else:  # overnight wraps around midnight
            if hour >= start or hour < end:
                return session
    return "unknown"


def parse_crontab() -> list[dict]:
    """Read user crontab and parse each entry."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().split("\n")
    except Exception:
        return []

    jobs = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Standard cron: min hour dom mon dow command
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            minute_field = parts[0]
            hour_field = parts[1]
            command = parts[5]
        except IndexError:
            continue

        # Extract script name from command
        script_match = re.search(r'([\w\-]+\.py)', command)
        script_name = script_match.group(1) if script_match else command.split("/")[-1]

        # Parse hour(s) — take first if comma-separated or range
        hour = None
        minute = None
        try:
            if hour_field == "*":
                hour = None
            elif "/" in hour_field:
                hour = int(hour_field.split("/")[0]) if hour_field.split("/")[0] != "*" else 0
            elif "," in hour_field:
                hour = int(hour_field.split(",")[0])
            elif "-" in hour_field:
                hour = int(hour_field.split("-")[0])
            else:
                hour = int(hour_field)
        except ValueError:
            hour = None

        try:
            if minute_field != "*" and "/" not in minute_field:
                minute = int(minute_field.split(",")[0])
        except ValueError:
            minute = None

        category = classify_category(script_name)
        session = classify_session(hour, minute)

        # Check if it runs frequently (every N minutes)
        is_frequent = "*/" in minute_field or (minute_field == "*" and hour_field == "*")

        jobs.append({
            "cron_line": line,
            "minute_field": minute_field,
            "hour_field": hour_field,
            "script_name": script_name,
            "category": category,
            "session": session,
            "hour": hour,
            "minute": minute,
            "is_frequent": is_frequent,
            "command": command,
        })

    return jobs


def assess_coverage(jobs: list[dict]) -> dict:
    """Determine which ATP-2 cadence slots are covered vs missing."""
    # Build sets of (category, session) from existing jobs
    existing_combos: set[tuple[str, str]] = set()
    for j in jobs:
        existing_combos.add((j["category"], j["session"]))

    coverage: dict[str, dict] = {}
    for slot, sig in ATP2_SLOT_SIGNATURES.items():
        matched_jobs = []
        for j in jobs:
            if j["category"] in sig["categories"] and j["session"] in sig["sessions"]:
                matched_jobs.append(j["script_name"])
        status = "covered" if matched_jobs else "missing"
        coverage[slot] = {
            "status": status,
            "expected_categories": sig["categories"],
            "expected_sessions": sig["sessions"],
            "matched_jobs": matched_jobs,
        }

    return coverage


def build_report(jobs: list[dict], coverage: dict, verbose: bool = False) -> dict:
    """Build the full inventory report."""
    # Group by category
    by_category: dict[str, list] = {}
    for j in jobs:
        cat = j["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append({
            "script": j["script_name"],
            "session": j["session"],
            "schedule": f"{j['minute_field']} {j['hour_field']}",
            "is_frequent": j["is_frequent"],
        })

    # Group by session
    by_session: dict[str, list] = {}
    for j in jobs:
        sess = j["session"]
        if sess not in by_session:
            by_session[sess] = []
        by_session[sess].append({
            "script": j["script_name"],
            "category": j["category"],
            "schedule": f"{j['minute_field']} {j['hour_field']}",
        })

    covered = [s for s, c in coverage.items() if c["status"] == "covered"]
    missing = [s for s, c in coverage.items() if c["status"] == "missing"]

    report = {
        "report": "ATP-2 Research Cadence Inventory",
        "generated_at": datetime.now().isoformat(),
        "total_cron_jobs": len(jobs),
        "categories_found": sorted(by_category.keys()),
        "sessions_found": sorted(by_session.keys()),
        "atp2_slots_covered": covered,
        "atp2_slots_missing": missing,
        "coverage_pct": round(len(covered) / len(ATP2_CADENCE_SLOTS) * 100, 1) if ATP2_CADENCE_SLOTS else 0,
        "by_category": by_category,
        "by_session": by_session,
        "slot_details": coverage,
    }

    if verbose:
        report["raw_jobs"] = [
            {"script": j["script_name"], "category": j["category"], "session": j["session"],
             "hour": j["hour"], "minute": j["minute"], "cron_line": j["cron_line"]}
            for j in jobs
        ]

    return report


def render_markdown(report: dict) -> str:
    """Render report as markdown."""
    lines = [
        f"# {report['report']}",
        f"Generated: {report['generated_at']}",
        "",
        f"**Total cron jobs:** {report['total_cron_jobs']}",
        f"**ATP-2 coverage:** {report['coverage_pct']}% ({len(report['atp2_slots_covered'])}/{len(ATP2_CADENCE_SLOTS)} slots)",
        "",
    ]

    if report["atp2_slots_missing"]:
        lines.append("## Missing ATP-2 Cadence Slots")
        for slot in report["atp2_slots_missing"]:
            detail = report["slot_details"][slot]
            lines.append(f"- **{slot}**: needs {', '.join(detail['expected_categories'])} in {', '.join(detail['expected_sessions'])}")
        lines.append("")

    if report["atp2_slots_covered"]:
        lines.append("## Covered ATP-2 Cadence Slots")
        for slot in report["atp2_slots_covered"]:
            detail = report["slot_details"][slot]
            lines.append(f"- **{slot}**: {', '.join(detail['matched_jobs'])}")
        lines.append("")

    lines.append("## Jobs by Category")
    for cat in sorted(report["by_category"].keys()):
        entries = report["by_category"][cat]
        lines.append(f"\n### {cat} ({len(entries)} jobs)")
        for e in entries:
            freq = " (frequent)" if e["is_frequent"] else ""
            lines.append(f"- `{e['script']}` [{e['session']}] {e['schedule']}{freq}")

    lines.append("")
    lines.append("## Jobs by Session Window")
    for sess in sorted(report["by_session"].keys()):
        entries = report["by_session"][sess]
        lines.append(f"\n### {sess} ({len(entries)} jobs)")
        for e in entries:
            lines.append(f"- `{e['script']}` [{e['category']}] {e['schedule']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ATP-2 Research Cadence Inventory Report")
    parser.add_argument("--output-json", type=str, help="Write JSON report to file")
    parser.add_argument("--output-md", type=str, help="Write Markdown report to file")
    parser.add_argument("--verbose", action="store_true", help="Include raw job details")
    args = parser.parse_args()

    print("[cadence-inventory] Reading crontab ...")
    jobs = parse_crontab()
    print(f"[cadence-inventory] Found {len(jobs)} cron jobs")

    coverage = assess_coverage(jobs)
    report = build_report(jobs, coverage, verbose=args.verbose)

    # Console summary
    covered = report["atp2_slots_covered"]
    missing = report["atp2_slots_missing"]
    print(f"[cadence-inventory] ATP-2 coverage: {report['coverage_pct']}%")
    if covered:
        print(f"[cadence-inventory] Covered: {', '.join(covered)}")
    if missing:
        print(f"[cadence-inventory] MISSING: {', '.join(missing)}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"[cadence-inventory] JSON written to {args.output_json}")

    if args.output_md:
        md = render_markdown(report)
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        print(f"[cadence-inventory] Markdown written to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
```
