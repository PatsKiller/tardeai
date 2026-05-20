#!/usr/bin/env python3
"""report_post_audit_ops1_integration_smoke.py — Integration smoke test across all audit reports.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def _safe_run(fn, label, verbose=False):
    """Run a report function, catching any errors."""
    try:
        return fn(verbose=verbose)
    except Exception as e:
        return {"error": str(e), "label": label}


def _status_from_root_cause(root_cause):
    """Derive a simple status from a root_cause string."""
    if root_cause is None:
        return "unknown"
    rc = root_cause.lower()
    if "none" in rc and ("healthy" in rc or "appears" in rc or "exist" in rc):
        return "healthy"
    if "not_found" in rc or "failed" in rc or "error" in rc:
        return "error"
    return "warning"


def run_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subsystems": {},
        "overall_health": "unknown",
    }

    # Import each report module
    from report_regime_cron1_staleness import run_report as regime_report
    from report_llm_fix1_overnight_fallback import run_report as llm_report
    from report_agent_fix1_queue_health import run_report as agent_report
    from report_count_truth1_drift_contract import run_report as count_report
    from report_attr1_benchmark_alpha import run_report as attr_report

    subsystem_fns = {
        "regime": ("Regime Cron Staleness", regime_report),
        "overnight": ("LLM Overnight Fallback", llm_report),
        "agent_queue": ("Agent Queue Health", agent_report),
        "count_truth": ("Count Truth Drift", count_report),
        "attribution": ("Attribution Benchmark", attr_report),
    }

    statuses = []
    for key, (label, fn) in subsystem_fns.items():
        result = _safe_run(fn, label, verbose=verbose)
        root_cause = result.get("root_cause") if isinstance(result, dict) else None
        status = _status_from_root_cause(root_cause)
        if "error" in result and not root_cause:
            status = "error"

        report["subsystems"][key] = {
            "label": label,
            "status": status,
            "root_cause": root_cause or result.get("error", "unknown"),
            "recommended_fix": result.get("recommended_fix"),
        }
        statuses.append(status)

    # --- Overall health ---
    if all(s == "healthy" for s in statuses):
        report["overall_health"] = "healthy"
    elif any(s == "error" for s in statuses):
        report["overall_health"] = "degraded"
    else:
        report["overall_health"] = "warning"

    if verbose:
        print("\n=== Post-Audit Integration Smoke Test ===")
        print(f"  Overall health: {report['overall_health']}")
        for key, info in report["subsystems"].items():
            print(f"  [{info['status'].upper():8s}] {info['label']}: {info['root_cause']}")

    return report


def main():
    p = argparse.ArgumentParser(description="Post-audit integration smoke test (read-only)")
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
            "# Post-Audit Integration Smoke Test",
            f"Generated: {report['generated_at']}",
            f"\n**Overall health: {report['overall_health']}**",
            "",
            "## Subsystem Status",
            "| Subsystem | Status | Root Cause | Fix |",
            "|-----------|--------|------------|-----|",
        ]
        for key, info in report["subsystems"].items():
            lines.append(
                f"| {info['label']} | {info['status']} | {info['root_cause']} | {info.get('recommended_fix', 'n/a')} |"
            )
        Path(args.output_md).write_text("\n".join(lines))
        print(f"Markdown written to {args.output_md}")


if __name__ == "__main__":
    main()
