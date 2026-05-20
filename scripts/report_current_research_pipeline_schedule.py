#!/usr/bin/env python3
"""report_current_research_pipeline_schedule.py — Crontab pipeline schedule report.

Read-only. No trades, no orders.

Usage:
    .venv/bin/python scripts/report_current_research_pipeline_schedule.py --verbose
    .venv/bin/python scripts/report_current_research_pipeline_schedule.py --output-json out.json --output-md out.md
"""
import argparse, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from db_adapter import _get_conn  # noqa: E402


# ── Classification helpers ──────────────────────────────────────────────

def _classify_session(minute: str, hour: str) -> str:
    """Classify cron time into a trading session bucket."""
    if minute.startswith("*/"):
        return "continuous"
    try:
        h = int(hour.split(",")[0].split("-")[0])
    except (ValueError, IndexError):
        return "continuous"
    if 4 <= h <= 7:
        return "premarket"
    if h == 8:
        return "market_open"
    if 9 <= h <= 15:
        return "market_hours"
    if 16 <= h <= 18:
        return "after_close"
    if 19 <= h <= 23 or 0 <= h <= 3:
        return "overnight"
    return "unknown"


_TYPE_PATTERNS = {
    "research": re.compile(
        r"screener|finviz|news|catalyst|enrichment|classify|discovery|intel",
        re.I,
    ),
    "execution": re.compile(
        r"paper_execution|paper_trade_monitor|alpaca|reconciler", re.I
    ),
    "governance": re.compile(r"governance|a1a|maturity|facts", re.I),
    "digest": re.compile(r"digest|brief|alert_digest|morning", re.I),
    "agent": re.compile(r"agent|watchlist_agent", re.I),
    "proposal": re.compile(r"promoter|proposal|sweep", re.I),
    "system": re.compile(r"health|backup|sync|config|regime|quote_refresh|data_gap", re.I),
}

_PROPOSAL_PATTERN = re.compile(r"promoter|auto_proposal|orchestrator", re.I)


def _classify_type(script_name: str) -> str:
    for label, pat in _TYPE_PATTERNS.items():
        if pat.search(script_name):
            return label
    return "other"


def _can_create_proposals(script_name: str) -> bool:
    return bool(_PROPOSAL_PATTERN.search(script_name))


# ── Crontab parsing ────────────────────────────────────────────────────

_SCRIPT_RE = re.compile(r"[\w/.-]+\.(?:py|sh)")


def _parse_crontab() -> list[dict]:
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return []

    jobs: list[dict] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 6:
            continue

        minute, hour, dom, month, dow = parts[:5]
        command = " ".join(parts[5:])

        # Extract script name(s)
        scripts_found = _SCRIPT_RE.findall(command)
        script_name = scripts_found[-1] if scripts_found else ""
        # Use just the basename for classification
        script_base = Path(script_name).name if script_name else command[:60]

        session = _classify_session(minute, hour)
        job_type = _classify_type(script_base)
        creates_proposals = _can_create_proposals(script_base)

        # Human-readable time
        if minute.startswith("*/"):
            time_str = f"every {minute[2:]} min"
            if hour != "*":
                time_str += f" (hours {hour})"
        else:
            time_str = f"{minute.zfill(2)}:{hour.zfill(2) if hour != '*' else '**'}"
            if dow != "*":
                time_str += f" (dow={dow})"

        jobs.append({
            "time": time_str,
            "minute": minute,
            "hour": hour,
            "dow": dow,
            "session": session,
            "type": job_type,
            "script": script_base,
            "can_create_proposals": creates_proposals,
            "raw": stripped,
        })

    return jobs


# ── Report builders ────────────────────────────────────────────────────

def _build_report(jobs: list[dict]) -> dict:
    # Summary by session
    session_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for j in jobs:
        session_counts[j["session"]] = session_counts.get(j["session"], 0) + 1
        type_counts[j["type"]] = type_counts.get(j["type"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_jobs": len(jobs),
        "jobs": jobs,
        "summary_by_session": dict(sorted(session_counts.items())),
        "summary_by_type": dict(sorted(type_counts.items())),
        "proposal_creators": [j["script"] for j in jobs if j["can_create_proposals"]],
    }


def _render_md(report: dict) -> str:
    lines = [
        "# Research Pipeline Schedule Report",
        f"Generated: {report['generated_at']}",
        f"Total cron jobs: {report['total_jobs']}",
        "",
        "## Jobs by Session",
        "",
        "| Time | Session | Type | Script | Creates Proposals |",
        "|------|---------|------|--------|-------------------|",
    ]
    for j in report["jobs"]:
        prop = "YES" if j["can_create_proposals"] else ""
        lines.append(
            f"| {j['time']} | {j['session']} | {j['type']} | {j['script']} | {prop} |"
        )

    lines += [
        "",
        "## Summary by Session",
        "",
        "| Session | Count |",
        "|---------|-------|",
    ]
    for k, v in report["summary_by_session"].items():
        lines.append(f"| {k} | {v} |")

    lines += [
        "",
        "## Summary by Type",
        "",
        "| Type | Count |",
        "|------|-------|",
    ]
    for k, v in report["summary_by_type"].items():
        lines.append(f"| {k} | {v} |")

    if report["proposal_creators"]:
        lines += [
            "",
            "## Proposal-Creating Scripts",
            "",
        ]
        for s in report["proposal_creators"]:
            lines.append(f"- {s}")

    lines.append("")
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Research pipeline schedule report (read-only)"
    )
    p.add_argument("--output-json", type=str, help="Write JSON report to path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    jobs = _parse_crontab()
    report = _build_report(jobs)

    if args.verbose:
        print(f"[pipeline-schedule] Parsed {len(jobs)} cron jobs")
        for k, v in report["summary_by_session"].items():
            print(f"  session={k}: {v}")
        for k, v in report["summary_by_type"].items():
            print(f"  type={k}: {v}")
        if report["proposal_creators"]:
            print(f"  proposal creators: {report['proposal_creators']}")

    if args.output_json:
        # Strip raw line from JSON output to keep it clean
        clean_jobs = [{k: v for k, v in j.items() if k != "raw"} for j in report["jobs"]]
        clean_report = {**report, "jobs": clean_jobs}
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(
            json.dumps(clean_report, indent=2, default=str) + "\n"
        )
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    if args.output_md:
        md = _render_md(report)
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md)
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    if not args.output_json and not args.output_md:
        print(_render_md(report))


if __name__ == "__main__":
    main()
