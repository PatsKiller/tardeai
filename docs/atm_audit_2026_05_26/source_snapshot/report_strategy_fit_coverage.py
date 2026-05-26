#!/usr/bin/env python3
"""report_strategy_fit_coverage.py — Strategy-fit audit coverage report.

Read-only. No trades. No orders. No alerts sent.

Usage:
    .venv/bin/python scripts/report_strategy_fit_coverage.py --latest --verbose
    .venv/bin/python scripts/report_strategy_fit_coverage.py --latest --output-json /tmp/fit_coverage.json
    .venv/bin/python scripts/report_strategy_fit_coverage.py --latest --output-md /tmp/fit_coverage.md
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            result = dict(zip([d[0] for d in cur.description], row)) if row else None
            conn.close()
            return result
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception as exc:
        if fetch == "all":
            return []
        return None


def _resolve_audit_run_id(args):
    """Return the audit_run_id to report on."""
    if getattr(args, "latest", False):
        row = _db_query(
            "SELECT audit_run_id FROM universe_strategy_fit_audit ORDER BY created_at DESC LIMIT 1",
            fetch="one",
        )
        if row:
            return row["audit_run_id"]
        return None
    return None


def _build_report(audit_run_id, verbose=False):
    report = {"audit_run_id": audit_run_id, "generated_at": datetime.now(timezone.utc).isoformat()}

    # Total symbols
    row = _db_query(
        "SELECT count(DISTINCT symbol) AS cnt FROM universe_strategy_fit_audit WHERE audit_run_id=%s",
        [audit_run_id], fetch="one",
    )
    report["total_symbols"] = row["cnt"] if row else 0

    # Total strategies
    row = _db_query(
        "SELECT count(DISTINCT strategy_id) AS cnt FROM universe_strategy_fit_audit WHERE audit_run_id=%s",
        [audit_run_id], fetch="one",
    )
    report["total_strategies"] = row["cnt"] if row else 0

    # Total evaluations
    row = _db_query(
        "SELECT count(*) AS cnt FROM universe_strategy_fit_audit WHERE audit_run_id=%s",
        [audit_run_id], fetch="one",
    )
    report["total_evaluations"] = row["cnt"] if row else 0

    # Match-strength distribution
    rows = _db_query(
        "SELECT match_strength, count(*) AS cnt FROM universe_strategy_fit_audit "
        "WHERE audit_run_id=%s GROUP BY match_strength ORDER BY count(*) DESC",
        [audit_run_id],
    )
    report["match_strength_distribution"] = {r["match_strength"]: r["cnt"] for r in rows}

    # Recommendation distribution
    rows = _db_query(
        "SELECT recommendation, count(*) AS cnt FROM universe_strategy_fit_audit "
        "WHERE audit_run_id=%s GROUP BY recommendation ORDER BY count(*) DESC",
        [audit_run_id],
    )
    report["recommendation_distribution"] = {r["recommendation"]: r["cnt"] for r in rows}

    # Top match by strategy
    rows = _db_query(
        "SELECT strategy_id, count(*) AS cnt FROM universe_strategy_fit_audit "
        "WHERE audit_run_id=%s AND top_match_for_symbol=TRUE GROUP BY strategy_id ORDER BY count(*) DESC",
        [audit_run_id],
    )
    report["top_match_by_strategy"] = {r["strategy_id"]: r["cnt"] for r in rows}

    # Strategies with zero top matches
    all_strategies = _db_query(
        "SELECT DISTINCT strategy_id FROM universe_strategy_fit_audit WHERE audit_run_id=%s",
        [audit_run_id],
    )
    all_ids = {r["strategy_id"] for r in all_strategies}
    top_ids = set(report["top_match_by_strategy"].keys())
    report["strategies_zero_top_matches"] = sorted(all_ids - top_ids)

    # Family gate rejections
    row = _db_query(
        "SELECT count(*) AS cnt FROM universe_strategy_fit_audit "
        "WHERE audit_run_id=%s AND family_gate_status='FAIL'",
        [audit_run_id], fetch="one",
    )
    report["family_gate_rejections"] = row["cnt"] if row else 0

    # Liquidity gate rejections
    row = _db_query(
        "SELECT count(*) AS cnt FROM universe_strategy_fit_audit "
        "WHERE audit_run_id=%s AND liquidity_gate_status='FAIL'",
        [audit_run_id], fetch="one",
    )
    report["liquidity_gate_rejections"] = row["cnt"] if row else 0

    return report


def _format_md(report):
    lines = [
        "# Strategy-Fit Coverage Report",
        "",
        f"**Audit Run ID:** `{report['audit_run_id']}`",
        f"**Generated:** {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Symbols | {report['total_symbols']} |",
        f"| Total Strategies | {report['total_strategies']} |",
        f"| Total Evaluations | {report['total_evaluations']} |",
        f"| Family Gate Rejections | {report['family_gate_rejections']} |",
        f"| Liquidity Gate Rejections | {report['liquidity_gate_rejections']} |",
        "",
        "## Match-Strength Distribution",
        "",
        "| Strength | Count |",
        "|----------|-------|",
    ]
    for k, v in report["match_strength_distribution"].items():
        lines.append(f"| {k} | {v} |")

    lines += [
        "",
        "## Recommendation Distribution",
        "",
        "| Recommendation | Count |",
        "|----------------|-------|",
    ]
    for k, v in report["recommendation_distribution"].items():
        lines.append(f"| {k} | {v} |")

    lines += [
        "",
        "## Top Match by Strategy",
        "",
        "| Strategy | Top-Match Count |",
        "|----------|-----------------|",
    ]
    for k, v in report["top_match_by_strategy"].items():
        lines.append(f"| {k} | {v} |")

    if report["strategies_zero_top_matches"]:
        lines += [
            "",
            "## Strategies With Zero Top Matches",
            "",
        ]
        for s in report["strategies_zero_top_matches"]:
            lines.append(f"- `{s}`")

    lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Strategy-fit audit coverage report (read-only)")
    p.add_argument("--latest", action="store_true", help="Use the latest audit_run_id")
    p.add_argument("--output-json", type=str, help="Write JSON report to this path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to this path")
    p.add_argument("--verbose", action="store_true", help="Print report to stdout")
    args = p.parse_args()

    audit_run_id = _resolve_audit_run_id(args)
    if not audit_run_id:
        print("ERROR: No audit_run_id found. Use --latest or ensure audit data exists.", file=sys.stderr)
        sys.exit(1)

    report = _build_report(audit_run_id, verbose=args.verbose)

    if args.verbose:
        print(json.dumps(report, indent=2, default=str))

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        print(f"JSON written to {args.output_json}")

    if args.output_md:
        md = _format_md(report)
        Path(args.output_md).write_text(md)
        print(f"Markdown written to {args.output_md}")

    if not args.verbose and not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
