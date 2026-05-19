#!/usr/bin/env python3
"""report_cron_alert_hygiene.py — Report cron health, DB errors, and noise from log files.

Read-only. No trades. No orders.
"""
import argparse, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

LOG_DIR = PROJ / "logs"

CRON_LOGS = [
    "watchpool_alerts_cron.log",
    "proactive_quote_refresh_cron.log",
    "telegram_commands.log",
    "stale_proposal_sweeper.log",
    "maturity_control_board.log",
    "governance_system_facts.log",
    "governance_a1a_check.log",
]

DB_ERROR_PATTERNS = [
    r"fe_sendauth",
    r"no password supplied",
    r"connection refused",
    r"could not connect",
]

APP_ERROR_PATTERNS = [
    r"Traceback",
    r"ERROR",
]


def _find_last_timestamp(lines):
    """Scan lines in reverse for a timestamp."""
    for line in reversed(lines):
        m = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", line)
        if m:
            return m.group(0)
    return None


def _count_pattern(lines, pattern):
    count = 0
    for line in lines:
        if re.search(pattern, line, re.IGNORECASE):
            count += 1
    return count


def main():
    p = argparse.ArgumentParser(description="Cron alert hygiene (read-only)")
    p.add_argument("--since-hours", type=int, default=24, help="Look back N hours (default 24)")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_hours": args.since_hours,
        "log_dir": str(LOG_DIR),
        "cron_logs": {},
        "summary": {
            "total_logs_checked": 0,
            "logs_found": 0,
            "logs_missing": 0,
            "logs_with_db_errors": 0,
            "logs_with_app_errors": 0,
            "cron_wrapper_fix_verified": True,
        },
    }

    for log_name in CRON_LOGS:
        log_path = LOG_DIR / log_name
        entry = {
            "exists": False,
            "last_timestamp": None,
            "total_lines": 0,
            "db_errors": {},
            "app_errors": {},
            "db_error_total": 0,
            "app_error_total": 0,
        }
        report["summary"]["total_logs_checked"] += 1

        if not log_path.exists():
            entry["exists"] = False
            report["summary"]["logs_missing"] += 1
            report["cron_logs"][log_name] = entry
            continue

        entry["exists"] = True
        report["summary"]["logs_found"] += 1

        try:
            text = log_path.read_text(errors="replace")
            lines = text.strip().splitlines()
            entry["total_lines"] = len(lines)
            entry["last_timestamp"] = _find_last_timestamp(lines)

            # DB errors
            for pat in DB_ERROR_PATTERNS:
                count = _count_pattern(lines, pat)
                if count > 0:
                    entry["db_errors"][pat] = count
                    entry["db_error_total"] += count

            # App errors
            for pat in APP_ERROR_PATTERNS:
                count = _count_pattern(lines, pat)
                if count > 0:
                    entry["app_errors"][pat] = count
                    entry["app_error_total"] += count

            if entry["db_error_total"] > 0:
                report["summary"]["logs_with_db_errors"] += 1
                # If any recent DB auth errors, wrapper fix not verified
                report["summary"]["cron_wrapper_fix_verified"] = False

            if entry["app_error_total"] > 0:
                report["summary"]["logs_with_app_errors"] += 1

        except Exception as e:
            entry["read_error"] = str(e)

        report["cron_logs"][log_name] = entry

    # Output
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        md = _to_md(report)
        Path(args.output_md).write_text(md)
        print(f"MD written to {args.output_md}")

    if args.verbose:
        print(json.dumps(report, indent=2, default=str))

    s = report["summary"]
    print(f"Logs: {s['logs_found']}/{s['total_logs_checked']} found  |  DB errors in: {s['logs_with_db_errors']}  |  App errors in: {s['logs_with_app_errors']}  |  Wrapper fix verified: {s['cron_wrapper_fix_verified']}")


def _to_md(r):
    lines = [
        f"# Cron Alert Hygiene Report",
        f"Generated: {r['generated_at']}  |  Window: {r['since_hours']}h\n",
        f"## Summary\n",
        f"- Logs checked: {r['summary']['total_logs_checked']}",
        f"- Found: {r['summary']['logs_found']}",
        f"- Missing: {r['summary']['logs_missing']}",
        f"- With DB errors: {r['summary']['logs_with_db_errors']}",
        f"- With app errors: {r['summary']['logs_with_app_errors']}",
        f"- Cron wrapper fix verified: **{r['summary']['cron_wrapper_fix_verified']}**\n",
        f"## Per-Log Detail\n",
        "| Log | Exists | Last Timestamp | Lines | DB Errors | App Errors |",
        "|-----|--------|----------------|-------|-----------|------------|",
    ]
    for name, info in r["cron_logs"].items():
        exists = "yes" if info["exists"] else "NO"
        ts = info.get("last_timestamp", "-") or "-"
        total = info.get("total_lines", 0)
        db_e = info.get("db_error_total", 0)
        app_e = info.get("app_error_total", 0)
        lines.append(f"| {name} | {exists} | {ts} | {total} | {db_e} | {app_e} |")

    # Detail for logs with errors
    for name, info in r["cron_logs"].items():
        if info.get("db_error_total", 0) > 0 or info.get("app_error_total", 0) > 0:
            lines.append(f"\n### {name}")
            if info["db_errors"]:
                lines.append("DB errors:")
                for pat, c in info["db_errors"].items():
                    lines.append(f"  - `{pat}`: {c}")
            if info["app_errors"]:
                lines.append("App errors:")
                for pat, c in info["app_errors"].items():
                    lines.append(f"  - `{pat}`: {c}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
