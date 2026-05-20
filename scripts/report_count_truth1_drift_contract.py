#!/usr/bin/env python3
"""report_count_truth1_drift_contract.py — Report count-truth drift contract across key sources.

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

STRATEGY_DIR = PROJ / "config" / "strategies"
EXCLUDED_YAMLS = {"recommendation_schema.yaml", "strategy_schema.yaml", "shared_risk_rules.yaml"}


def _count_strategy_yamls():
    """Count YAML files in config/strategies/ excluding schema/shared."""
    if not STRATEGY_DIR.is_dir():
        return 0
    count = 0
    for f in STRATEGY_DIR.iterdir():
        if f.suffix in (".yaml", ".yml") and f.name not in EXCLUDED_YAMLS:
            count += 1
    return count


def run_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_rows": [],
        "root_cause": None,
        "recommended_fix": None,
    }

    conn = _get_conn()
    if not conn:
        report["root_cause"] = "db_connection_failed"
        if verbose:
            _print_report(report)
        return report

    queries = [
        {
            "source_table": "paper_trades",
            "filter": "status = 'closed'",
            "sql": "SELECT COUNT(*) FROM paper_trades WHERE status = 'closed'",
            "label": "paper_trades_closed",
        },
        {
            "source_table": "paper_trades",
            "filter": "status != 'closed'",
            "sql": "SELECT COUNT(*) FROM paper_trades WHERE status != 'closed'",
            "label": "paper_trades_open",
        },
        {
            "source_table": "incubator_universe",
            "filter": "active = true",
            "sql": "SELECT COUNT(*) FROM incubator_universe WHERE active = true",
            "label": "incubator_active",
        },
        {
            "source_table": "paper_trade_proposals",
            "filter": "status = 'pending'",
            "sql": "SELECT COUNT(*) FROM paper_trade_proposals WHERE status = 'pending' OR status = 'PENDING'",
            "label": "proposals_pending",
        },
        {
            "source_table": "watchlist_agent_jobs",
            "filter": "status = 'queued'",
            "sql": "SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status = 'queued'",
            "label": "agent_jobs_queued",
        },
        {
            "source_table": "deep_overnight_llm_queue",
            "filter": "status = 'pending'",
            "sql": "SELECT COUNT(*) FROM deep_overnight_llm_queue WHERE status = 'pending'",
            "label": "overnight_llm_pending",
        },
    ]

    try:
        cur = conn.cursor()
        for q in queries:
            try:
                cur.execute(q["sql"])
                count = cur.fetchone()[0]
            except Exception as e:
                count = None
                conn.rollback()
            report["contract_rows"].append({
                "source_table": q["source_table"],
                "filter": q["filter"],
                "count": count,
                "recommended_label": q["label"],
            })
        cur.close()
    except Exception as e:
        report["root_cause"] = f"query_error: {e}"

    # Strategy YAML count (filesystem source)
    yaml_count = _count_strategy_yamls()
    report["contract_rows"].append({
        "source_table": "config/strategies/*.yaml",
        "filter": "excluding schema/shared",
        "count": yaml_count,
        "recommended_label": "strategy_configs",
    })

    # --- Root cause analysis ---
    if report["root_cause"] is None:
        null_counts = [r for r in report["contract_rows"] if r["count"] is None]
        zero_counts = [r for r in report["contract_rows"] if r["count"] == 0]
        issues = []
        if null_counts:
            issues.append(f"{len(null_counts)} source(s) failed to query: "
                          + ", ".join(r["recommended_label"] for r in null_counts))
        if zero_counts:
            issues.append(f"{len(zero_counts)} source(s) returned 0: "
                          + ", ".join(r["recommended_label"] for r in zero_counts))
        if issues:
            report["root_cause"] = "; ".join(issues)
        else:
            report["root_cause"] = "none — all count sources returned data"

    report["recommended_fix"] = (
        "investigate missing/zero sources" if "failed" in (report["root_cause"] or "")
        else "none"
    )

    if verbose:
        _print_report(report)

    return report


def _print_report(report):
    print("=== Count Truth Drift Contract Report ===")
    for row in report["contract_rows"]:
        print(f"  {row['recommended_label']}: {row['count']}  ({row['source_table']} WHERE {row['filter']})")
    print(f"  Root cause: {report['root_cause']}")
    print(f"  Fix: {report['recommended_fix']}")


def main():
    p = argparse.ArgumentParser(description="Count truth drift contract report (read-only)")
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
            "# Count Truth Drift Contract Report",
            f"Generated: {report['generated_at']}",
            "",
            "## Contract Table",
            "| Source | Filter | Count | Label |",
            "|--------|--------|-------|-------|",
        ]
        for row in report["contract_rows"]:
            lines.append(f"| {row['source_table']} | {row['filter']} | {row['count']} | {row['recommended_label']} |")
        lines.append(f"\n## Root Cause\n- {report['root_cause'] or 'none'}")
        lines.append(f"\n## Recommended Fix\n- {report['recommended_fix'] or 'none'}")
        Path(args.output_md).write_text("\n".join(lines))
        print(f"Markdown written to {args.output_md}")


if __name__ == "__main__":
    main()
