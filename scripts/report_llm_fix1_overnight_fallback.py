#!/usr/bin/env python3
"""report_llm_fix1_overnight_fallback.py — Report overnight recovery verdict quality and LLM health.

Read-only. No trades. No orders.
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
        "table_exists": False,
        "verdict_count_7d": 0,
        "distinct_verdict_count_7d": 0,
        "template_fallback_detected": False,
        "ollama_reachable": False,
        "root_cause": None,
        "recommended_fix": None,
    }

    # --- Check overnight_recovery_verdicts table ---
    conn = _get_conn()
    if not conn:
        report["root_cause"] = "db_connection_failed"
        if verbose:
            _print_report(report)
        return report

    try:
        cur = conn.cursor()
        # Check table existence
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_name = 'overnight_recovery_verdicts'"
            ")"
        )
        report["table_exists"] = cur.fetchone()[0]

        if not report["table_exists"]:
            report["root_cause"] = "table_not_found"
            cur.close()
            if verbose:
                _print_report(report)
            return report

        # Count total verdicts in last 7 days
        cur.execute(
            "SELECT COUNT(*) FROM overnight_recovery_verdicts "
            "WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        report["verdict_count_7d"] = cur.fetchone()[0]

        # Count distinct verdict_text in last 7 days
        cur.execute(
            "SELECT COUNT(DISTINCT verdict_text) FROM overnight_recovery_verdicts "
            "WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        report["distinct_verdict_count_7d"] = cur.fetchone()[0]

        # Detect template fallback: if total > distinct * 0.9 => mostly duplicates
        total = report["verdict_count_7d"]
        distinct = report["distinct_verdict_count_7d"]
        if total > 0 and distinct > 0 and total > distinct * 0.9:
            report["template_fallback_detected"] = True

        cur.close()
    except Exception as e:
        report["root_cause"] = f"query_error: {e}"
        conn.rollback()

    # --- Check Ollama reachability ---
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            report["ollama_reachable"] = True
    except Exception:
        pass

    # --- Determine root cause ---
    if report["root_cause"] is None:
        issues = []
        if report["verdict_count_7d"] == 0:
            issues.append("no verdicts in last 7 days")
        if report["template_fallback_detected"]:
            issues.append("template fallback detected — verdicts lack diversity")
        if not report["ollama_reachable"]:
            issues.append("ollama not reachable at localhost:11434")
        if issues:
            report["root_cause"] = "; ".join(issues)
        else:
            report["root_cause"] = "none — overnight LLM pipeline appears healthy"

    # --- Recommended fix ---
    if report["template_fallback_detected"] and not report["ollama_reachable"]:
        report["recommended_fix"] = "start ollama service; verdicts are using static template fallback"
    elif report["template_fallback_detected"]:
        report["recommended_fix"] = "check LLM prompt diversity; ollama is up but verdicts are repetitive"
    elif not report["ollama_reachable"]:
        report["recommended_fix"] = "start ollama service (systemctl start ollama)"
    elif report["verdict_count_7d"] == 0:
        report["recommended_fix"] = "check overnight recovery pipeline scheduling"
    else:
        report["recommended_fix"] = "none"

    if verbose:
        _print_report(report)

    return report


def _print_report(report):
    print("=== LLM Overnight Fallback Report ===")
    print(f"  Table exists: {report['table_exists']}")
    print(f"  Verdict count (7d): {report['verdict_count_7d']}")
    print(f"  Distinct verdicts (7d): {report['distinct_verdict_count_7d']}")
    print(f"  Template fallback detected: {report['template_fallback_detected']}")
    print(f"  Ollama reachable: {report['ollama_reachable']}")
    print(f"  Root cause: {report['root_cause']}")
    print(f"  Fix: {report['recommended_fix']}")


def main():
    p = argparse.ArgumentParser(description="LLM overnight fallback report (read-only)")
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
            "# LLM Overnight Fallback Report",
            f"Generated: {report['generated_at']}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Table exists | {report['table_exists']} |",
            f"| Verdict count (7d) | {report['verdict_count_7d']} |",
            f"| Distinct verdicts (7d) | {report['distinct_verdict_count_7d']} |",
            f"| Template fallback | {report['template_fallback_detected']} |",
            f"| Ollama reachable | {report['ollama_reachable']} |",
            "",
            f"## Root Cause\n- {report['root_cause'] or 'none'}",
            f"\n## Recommended Fix\n- {report['recommended_fix'] or 'none'}",
        ]
        Path(args.output_md).write_text("\n".join(lines))
        print(f"Markdown written to {args.output_md}")


if __name__ == "__main__":
    main()
