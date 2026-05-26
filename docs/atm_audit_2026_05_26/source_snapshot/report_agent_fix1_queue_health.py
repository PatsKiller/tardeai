#!/usr/bin/env python3
"""report_agent_fix1_queue_health.py — Report watchlist agent job queue health.

Read-only. No trades. No orders.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn


def run_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_counts": {},
        "oldest_queued": None,
        "worker_running": False,
        "root_cause": None,
        "recommended_fix": None,
    }

    conn = _get_conn()
    if not conn:
        report["root_cause"] = "db_connection_failed"
        if verbose:
            _print_report(report)
        return report

    try:
        cur = conn.cursor()

        # Status breakdown for last 7 days
        cur.execute(
            "SELECT status, count(*) FROM watchlist_agent_jobs "
            "WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY status"
        )
        for row in cur.fetchall():
            report["status_counts"][row[0]] = row[1]

        # Oldest queued job
        cur.execute(
            "SELECT MIN(created_at) FROM watchlist_agent_jobs WHERE status='queued'"
        )
        row = cur.fetchone()
        if row and row[0]:
            report["oldest_queued"] = row[0].isoformat()

        cur.close()
    except Exception as e:
        report["root_cause"] = f"query_error: {e}"
        conn.rollback()

    # --- Check if worker process is running ---
    try:
        result = subprocess.run(
            ["pgrep", "-f", "process_watchlist_agent_jobs"],
            capture_output=True, text=True, timeout=10
        )
        report["worker_running"] = result.returncode == 0
    except Exception:
        pass

    # --- Determine root cause ---
    if report["root_cause"] is None:
        issues = []
        queued = report["status_counts"].get("queued", 0)
        failed = report["status_counts"].get("failed", 0)
        completed = report["status_counts"].get("completed", 0)

        if not report["worker_running"]:
            issues.append("worker process not running")
        if queued > 50:
            issues.append(f"queue backlog: {queued} queued jobs")
        if failed > 0 and completed > 0 and failed / (failed + completed) > 0.2:
            issues.append(f"high failure rate: {failed}/{failed + completed}")
        elif failed > 0 and completed == 0:
            issues.append(f"{failed} failed jobs with 0 completed")

        if report["oldest_queued"]:
            oldest = datetime.fromisoformat(report["oldest_queued"])
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - oldest).total_seconds() / 3600
            if age_hours > 24:
                issues.append(f"oldest queued job is {age_hours:.1f}h old")

        if issues:
            report["root_cause"] = "; ".join(issues)
        else:
            report["root_cause"] = "none — agent queue appears healthy"

    # --- Recommended fix ---
    if not report["worker_running"]:
        report["recommended_fix"] = "start the agent job worker process"
    elif report["status_counts"].get("failed", 0) > 10:
        report["recommended_fix"] = "investigate failed jobs for common error patterns"
    elif report["status_counts"].get("queued", 0) > 50:
        report["recommended_fix"] = "scale worker or investigate processing bottleneck"
    else:
        report["recommended_fix"] = "none"

    if verbose:
        _print_report(report)

    return report


def _print_report(report):
    print("=== Agent Queue Health Report ===")
    print(f"  Status counts: {report['status_counts']}")
    print(f"  Oldest queued: {report['oldest_queued']}")
    print(f"  Worker running: {report['worker_running']}")
    print(f"  Root cause: {report['root_cause']}")
    print(f"  Fix: {report['recommended_fix']}")


def main():
    p = argparse.ArgumentParser(description="Agent queue health report (read-only)")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    report = run_report(verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        lines = [
            "# Agent Queue Health Report",
            f"Generated: {report['generated_at']}",
            "",
            "## Status Counts (7 days)",
            "| Status | Count |",
            "|--------|-------|",
        ]
        for status, count in sorted(report["status_counts"].items()):
            lines.append(f"| {status} | {count} |")
        lines.append(f"\n## Queue State")
        lines.append(f"- **Oldest queued:** {report['oldest_queued'] or 'none'}")
        lines.append(f"- **Worker running:** {report['worker_running']}")
        lines.append(f"\n## Root Cause\n- {report['root_cause'] or 'none'}")
        lines.append(f"\n## Recommended Fix\n- {report['recommended_fix'] or 'none'}")
        Path(args.output_md).write_text("\n".join(lines))
        print(f"Markdown written to {args.output_md}")


if __name__ == "__main__":
    main()
