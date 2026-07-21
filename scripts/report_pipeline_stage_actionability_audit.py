"""
report_pipeline_stage_actionability_audit.py — Audit each pipeline stage for actionability.

Read-only. No trades, no orders.

For each of 31 stages: checks cron presence, pipeline_runs telemetry, log existence,
and scores actionability 0-100.

Usage:
    python scripts/report_pipeline_stage_actionability_audit.py --output-json audit.json --output-md audit.md --verbose
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv; load_dotenv(PROJ / ".env")

from pipeline_stage_owner_map import get_all_stages

# ─────────────────────────────────────────────────────────────────────────────
# DB helper (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _get_db_connection():
    import psycopg2
    return psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        dbname="trade_ai",
        user="trade_ai",
        password=os.getenv("DB_PASSWORD", ""),
    )


def _query_pipeline_runs(pipeline_key: str) -> dict | None:
    """Return latest pipeline_runs row for this key, or None."""
    try:
        conn = _get_db_connection()
        conn.set_session(readonly=True)
        cur = conn.cursor()
        cur.execute(
            """SELECT pipeline_key, status, started_at, finished_at,
                      duration_seconds, summary
               FROM pipeline_runs
               WHERE pipeline_key = %s
               ORDER BY started_at DESC LIMIT 1""",
            [pipeline_key],
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "pipeline_key": row[0],
                "status": row[1],
                "started_at": row[2].isoformat() if row[2] else None,
                "finished_at": row[3].isoformat() if row[3] else None,
                "duration_seconds": float(row[4]) if row[4] is not None else None,
                "summary": row[5] if row[5] else None,
            }
        return None
    except Exception as e:
        return {"_error": str(e)}


def _count_pipeline_runs(pipeline_key: str) -> int:
    """Return total count of pipeline_runs rows for this key."""
    try:
        conn = _get_db_connection()
        conn.set_session(readonly=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline_key = %s",
            [pipeline_key],
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Cron detection
# ─────────────────────────────────────────────────────────────────────────────

_CRONTAB_CACHE: list[str] | None = None


def _load_crontab() -> list[str]:
    global _CRONTAB_CACHE
    if _CRONTAB_CACHE is not None:
        return _CRONTAB_CACHE
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10
        )
        _CRONTAB_CACHE = result.stdout.splitlines() if result.returncode == 0 else []
    except Exception:
        _CRONTAB_CACHE = []
    return _CRONTAB_CACHE


def _cron_exists_for(owning_script: str | None) -> bool:
    """Check if the owning_script name appears in crontab."""
    if not owning_script:
        return False
    lines = _load_crontab()
    # Extract just the filename from "scripts/foo.py"
    script_name = Path(owning_script).name
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if script_name in stripped:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Log existence
# ─────────────────────────────────────────────────────────────────────────────

def _log_exists(log_paths: list[str]) -> bool:
    """Return True if at least one log file exists on disk."""
    for lp in log_paths:
        full = PROJ / lp
        if full.exists() and full.stat().st_size > 0:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Execution-stage detection
# ─────────────────────────────────────────────────────────────────────────────

_EXECUTION_ON_DEMAND_KEYS = {"risk_gate", "tradeai_automated"}


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def _score_stage(stage: dict, cron_found: bool, telemetry_row: dict | None,
                 run_count: int, log_found: bool) -> dict:
    """
    Score a stage 0-100:
      +20 if owner known (owning_script is not None)
      +20 if cron found
      +20 if telemetry present (pipeline_runs has rows)
      +20 if log exists on disk
      +20 if safe action available (safe_dry_run_cmd is not None)
    """
    key = stage["pipeline_key"]
    is_execution = key in _EXECUTION_ON_DEMAND_KEYS

    score = 0
    details = {}

    # 1. Owner known
    has_owner = stage["owning_script"] is not None
    if has_owner:
        score += 20
    details["owner_known"] = has_owner

    # 2. Cron found
    details["cron_found"] = cron_found
    if cron_found:
        score += 20

    # 3. Telemetry present
    has_telemetry = run_count > 0 and (telemetry_row is None or "_error" not in telemetry_row)
    if telemetry_row and "_error" in telemetry_row:
        has_telemetry = False
    details["telemetry_present"] = has_telemetry
    details["run_count"] = run_count
    if has_telemetry:
        score += 20

    # 4. Log exists
    details["log_exists"] = log_found
    if log_found:
        score += 20

    # 5. Safe action available
    has_action = stage["safe_dry_run_cmd"] is not None
    details["safe_action_available"] = has_action
    if has_action:
        score += 20

    details["score"] = score

    # Classification
    if is_execution:
        classification = "ON_DEMAND"
    elif score >= 80:
        classification = "ACTIONABLE"
    elif score >= 40:
        classification = "PARTIALLY_ACTIONABLE"
    else:
        classification = "NOT_ACTIONABLE"
    details["classification"] = classification

    # Never-run subtype
    never_run_subtype = None
    if not has_telemetry:
        if is_execution:
            never_run_subtype = "never_run_on_demand"
        elif not has_owner:
            never_run_subtype = "never_run_owner_unknown"
        elif not cron_found and stage["cron_pattern"] is not None:
            never_run_subtype = "never_run_cron_missing"
        elif cron_found and stage["cron_pattern"] is not None:
            never_run_subtype = "never_run_waiting_for_schedule"
        else:
            never_run_subtype = "never_run_telemetry_missing"
    details["never_run_subtype"] = never_run_subtype

    # Latest run info
    if telemetry_row and "_error" not in telemetry_row:
        details["last_status"] = telemetry_row.get("status")
        details["last_run_at"] = telemetry_row.get("started_at")
    else:
        details["last_status"] = None
        details["last_run_at"] = None

    return details


# ─────────────────────────────────────────────────────────────────────────────
# Main audit
# ─────────────────────────────────────────────────────────────────────────────

def run_audit(verbose: bool = False) -> dict:
    stages = get_all_stages()
    results = []

    for stage in stages:
        key = stage["pipeline_key"]
        if verbose:
            print(f"  Checking {key}...", end=" ", flush=True)

        cron_found = _cron_exists_for(stage["owning_script"])
        # Also check wrapper
        if not cron_found and stage["owning_wrapper"]:
            cron_found = _cron_exists_for(stage["owning_wrapper"])

        telemetry_row = _query_pipeline_runs(key)
        run_count = _count_pipeline_runs(key)
        log_found = _log_exists(stage["log_paths"])

        score_details = _score_stage(stage, cron_found, telemetry_row, run_count, log_found)

        entry = {
            "pipeline_key": key,
            "display_name": stage["display_name"],
            "category": stage["category"],
            "owning_script": stage["owning_script"],
            "cron_pattern": stage["cron_pattern"],
            **score_details,
        }
        results.append(entry)

        if verbose:
            cls = score_details["classification"]
            sc = score_details["score"]
            sub = score_details.get("never_run_subtype") or ""
            print(f"score={sc}  {cls}  {sub}")

    # Build summary
    total = len(results)
    by_classification = {}
    by_never_run_subtype = {}
    by_category = {}

    for r in results:
        cls = r["classification"]
        by_classification[cls] = by_classification.get(cls, 0) + 1

        sub = r.get("never_run_subtype")
        if sub:
            by_never_run_subtype[sub] = by_never_run_subtype.get(sub, 0) + 1

        cat = r["category"]
        by_category.setdefault(cat, {"total": 0, "actionable": 0, "partial": 0, "not_actionable": 0, "on_demand": 0})
        by_category[cat]["total"] += 1
        if r["classification"] == "ACTIONABLE":
            by_category[cat]["actionable"] += 1
        elif r["classification"] == "PARTIALLY_ACTIONABLE":
            by_category[cat]["partial"] += 1
        elif r["classification"] == "NOT_ACTIONABLE":
            by_category[cat]["not_actionable"] += 1
        elif r["classification"] == "ON_DEMAND":
            by_category[cat]["on_demand"] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_stages": total,
            "by_classification": by_classification,
            "by_never_run_subtype": by_never_run_subtype,
            "by_category": by_category,
        },
        "stages": results,
    }
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Markdown renderer
# ─────────────────────────────────────────────────────────────────────────────

def _render_md(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Pipeline Stage Actionability Audit",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Total stages:** {s['total_stages']}",
        "",
        "## Classification Summary",
        "",
        "| Classification | Count |",
        "|---|---|",
    ]
    for cls, count in sorted(s["by_classification"].items()):
        lines.append(f"| {cls} | {count} |")

    if s["by_never_run_subtype"]:
        lines.extend([
            "",
            "## Never-Run Subtypes",
            "",
            "| Subtype | Count |",
            "|---|---|",
        ])
        for sub, count in sorted(s["by_never_run_subtype"].items()):
            lines.append(f"| {sub} | {count} |")

    lines.extend([
        "",
        "## By Category",
        "",
        "| Category | Total | Actionable | Partial | Not Actionable | On-Demand |",
        "|---|---|---|---|---|---|",
    ])
    for cat, vals in s["by_category"].items():
        lines.append(
            f"| {cat} | {vals['total']} | {vals['actionable']} | "
            f"{vals['partial']} | {vals['not_actionable']} | {vals['on_demand']} |"
        )

    lines.extend(["", "## Per-Stage Details", ""])
    for st in report["stages"]:
        icon = {
            "ACTIONABLE": "[OK]",
            "PARTIALLY_ACTIONABLE": "[PARTIAL]",
            "NOT_ACTIONABLE": "[MISSING]",
            "ON_DEMAND": "[ON-DEMAND]",
        }.get(st["classification"], "?")
        lines.append(f"### {icon} {st['display_name']} (`{st['pipeline_key']}`)")
        lines.append(f"- **Category:** {st['category']}")
        lines.append(f"- **Score:** {st['score']}/100 -- {st['classification']}")
        lines.append(f"- **Owner:** `{st['owning_script'] or 'N/A'}` | owner_known={st['owner_known']}")
        lines.append(f"- **Cron:** {st['cron_pattern'] or 'N/A'} | cron_found={st['cron_found']}")
        lines.append(f"- **Telemetry:** run_count={st['run_count']} | last_status={st['last_status']} | last_run={st['last_run_at']}")
        lines.append(f"- **Log on disk:** {st['log_exists']}")
        lines.append(f"- **Safe action:** {st['safe_action_available']}")
        if st.get("never_run_subtype"):
            lines.append(f"- **Never-run subtype:** {st['never_run_subtype']}")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pipeline stage actionability audit")
    parser.add_argument("--output-json", type=str, help="Write JSON report to this path")
    parser.add_argument("--output-md", type=str, help="Write Markdown report to this path")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stdout")
    args = parser.parse_args()

    if args.verbose:
        print("Pipeline Stage Actionability Audit")
        print("=" * 50)
        print()

    report = run_audit(verbose=args.verbose)

    if args.verbose:
        s = report["summary"]
        print()
        print(f"Total stages: {s['total_stages']}")
        print(f"By classification: {json.dumps(s['by_classification'])}")
        if s["by_never_run_subtype"]:
            print(f"Never-run subtypes: {json.dumps(s['by_never_run_subtype'])}")
        print()

    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {path}")

    if args.output_md:
        path = Path(args.output_md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_md(report))
        print(f"Markdown written to {path}")

    if not args.output_json and not args.output_md and not args.verbose:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
