#!/usr/bin/env python3
"""report_llm_fix1_overnight_fallback.py — Report overnight LLM verdict quality and pipeline health.

Read-only. No trades. No orders.

LLM-FIX-1 correction: the original diagnosis referenced `overnight_recovery_verdicts`
which never existed. The actual pipeline uses:
  - deep_overnight_llm_queue (1636 jobs queued)
  - deep_overnight_llm_results (1116 results with real LLM verdicts)
  - overnight_actionable_outcomes (populated from results)
"""
import argparse, json, sys
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
        "queue_table_exists": False,
        "results_table_exists": False,
        "actionable_table_exists": False,
        "queue_total": 0,
        "queue_done": 0,
        "queue_pending": 0,
        "queue_failed": 0,
        "results_total": 0,
        "results_7d": 0,
        "results_distinct_summaries_7d": 0,
        "recovery_verdicts_7d": 0,
        "actionable_outcomes_total": 0,
        "template_fallback_detected": False,
        "ollama_reachable": False,
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

        # Check table existence
        for table, key in [("deep_overnight_llm_queue", "queue_table_exists"),
                           ("deep_overnight_llm_results", "results_table_exists"),
                           ("overnight_actionable_outcomes", "actionable_table_exists")]:
            cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)", [table])
            report[key] = cur.fetchone()[0]

        if not report["results_table_exists"]:
            report["root_cause"] = "results_table_not_found"
            if verbose:
                _print_report(report)
            return report

        # Queue stats
        if report["queue_table_exists"]:
            cur.execute("SELECT status, COUNT(*) FROM deep_overnight_llm_queue GROUP BY status")
            for status, cnt in cur.fetchall():
                report["queue_total"] += cnt
                if status == "done":
                    report["queue_done"] = cnt
                elif status == "pending":
                    report["queue_pending"] = cnt
                elif status in ("failed", "error"):
                    report["queue_failed"] += cnt

        # Results stats
        cur.execute("SELECT COUNT(*) FROM deep_overnight_llm_results")
        report["results_total"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM deep_overnight_llm_results WHERE created_at > NOW() - INTERVAL '7 days'")
        report["results_7d"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT LEFT(summary, 200)) FROM deep_overnight_llm_results WHERE created_at > NOW() - INTERVAL '7 days'")
        report["results_distinct_summaries_7d"] = cur.fetchone()[0]

        # Recovery watch verdicts
        cur.execute("SELECT COUNT(*) FROM deep_overnight_llm_results WHERE job_type='recovery_watch_review' AND created_at > NOW() - INTERVAL '7 days'")
        report["recovery_verdicts_7d"] = cur.fetchone()[0]

        # Actionable outcomes
        if report["actionable_table_exists"]:
            cur.execute("SELECT COUNT(*) FROM overnight_actionable_outcomes")
            report["actionable_outcomes_total"] = cur.fetchone()[0]

        # Template fallback detection: if many results but all have identical summaries
        total = report["results_7d"]
        distinct = report["results_distinct_summaries_7d"]
        if total > 10 and distinct > 0 and distinct < total * 0.1:
            report["template_fallback_detected"] = True

        cur.close()
    except Exception as e:
        report["root_cause"] = f"query_error: {e}"
        try:
            conn.rollback()
        except Exception:
            pass

    # Check Ollama reachability
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status == 200:
            report["ollama_reachable"] = True
    except Exception:
        pass

    # Determine root cause
    if report["root_cause"] is None:
        issues = []
        if report["results_7d"] == 0:
            issues.append("no results in last 7 days")
        if report["template_fallback_detected"]:
            issues.append("template fallback detected — results lack diversity")
        if not report["ollama_reachable"]:
            issues.append("ollama not reachable at localhost:11434")
        if report["actionable_outcomes_total"] == 0 and report["results_total"] > 0:
            issues.append("actionable outcome extraction not wired (results exist but outcomes empty)")
        if issues:
            report["root_cause"] = "; ".join(issues)
        else:
            report["root_cause"] = "none — overnight LLM pipeline appears healthy"

    # Recommended fix
    if not report["ollama_reachable"]:
        report["recommended_fix"] = "start ollama service"
    elif report["results_7d"] == 0:
        report["recommended_fix"] = "check overnight queue scheduling and LLM availability"
    elif report["template_fallback_detected"]:
        report["recommended_fix"] = "check LLM prompt diversity"
    elif report["actionable_outcomes_total"] == 0:
        report["recommended_fix"] = "wire actionable outcome extraction from deep_overnight_llm_results"
    else:
        report["recommended_fix"] = "none"

    if verbose:
        _print_report(report)

    conn.close()
    return report


def _print_report(report):
    print("=== Overnight LLM Pipeline Report ===")
    print(f"  Queue: {report['queue_total']} total, {report['queue_done']} done, {report['queue_pending']} pending, {report['queue_failed']} failed")
    print(f"  Results: {report['results_total']} total, {report['results_7d']} in 7d, {report['results_distinct_summaries_7d']} distinct")
    print(f"  Recovery verdicts (7d): {report['recovery_verdicts_7d']}")
    print(f"  Actionable outcomes: {report['actionable_outcomes_total']}")
    print(f"  Template fallback: {report['template_fallback_detected']}")
    print(f"  Ollama reachable: {report['ollama_reachable']}")
    print(f"  Root cause: {report['root_cause']}")
    print(f"  Fix: {report['recommended_fix']}")


def main():
    p = argparse.ArgumentParser(description="Overnight LLM pipeline report (read-only)")
    p.add_argument("--output-json", type=str, help="Path to write JSON report")
    p.add_argument("--output-md", type=str, help="Path to write Markdown report")
    p.add_argument("--verbose", action="store_true", help="Print verbose summary")
    args = p.parse_args()

    report = run_report(verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Overnight LLM Pipeline Report",
            f"Generated: {report['generated_at']}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Queue total | {report['queue_total']} |",
            f"| Queue done | {report['queue_done']} |",
            f"| Queue pending | {report['queue_pending']} |",
            f"| Results total | {report['results_total']} |",
            f"| Results 7d | {report['results_7d']} |",
            f"| Recovery verdicts 7d | {report['recovery_verdicts_7d']} |",
            f"| Actionable outcomes | {report['actionable_outcomes_total']} |",
            f"| Template fallback | {report['template_fallback_detected']} |",
            f"| Ollama reachable | {report['ollama_reachable']} |",
            "",
            f"## Root Cause\n{report['root_cause'] or 'none'}",
            f"\n## Recommended Fix\n{report['recommended_fix'] or 'none'}",
        ]
        Path(args.output_md).write_text("\n".join(lines))


if __name__ == "__main__":
    main()
