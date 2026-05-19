#!/usr/bin/env python3
"""report_strategy_fit_data_gaps.py — Identify data gaps in strategy-fit audit.

Read-only. No trades. No orders. No alerts sent.

Usage:
    .venv/bin/python scripts/report_strategy_fit_data_gaps.py --latest --verbose
    .venv/bin/python scripts/report_strategy_fit_data_gaps.py --latest --output-json /tmp/data_gaps.json
    .venv/bin/python scripts/report_strategy_fit_data_gaps.py --latest --output-md /tmp/data_gaps.md
"""
import argparse, json, sys
from collections import Counter
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
    except Exception:
        return [] if fetch == "all" else None


def _resolve_latest_run_id():
    row = _db_query(
        "SELECT audit_run_id FROM universe_strategy_fit_audit ORDER BY created_at DESC LIMIT 1",
        fetch="one",
    )
    return row["audit_run_id"] if row else None


def _parse_missing_fields(raw):
    """Parse the missing_fields JSON text column into a list of strings."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def _build_report(audit_run_id, verbose=False):
    report = {"audit_run_id": audit_run_id, "generated_at": datetime.now(timezone.utc).isoformat()}

    # Rows with incomplete data or non-empty missing_fields
    rows = _db_query(
        "SELECT symbol, strategy_id, required_data_status, missing_fields "
        "FROM universe_strategy_fit_audit "
        "WHERE audit_run_id=%s AND ("
        "  required_data_status != 'COMPLETE' "
        "  OR (missing_fields IS NOT NULL AND missing_fields != '' AND missing_fields != '[]')"
        ")",
        [audit_run_id],
    )

    report["total_rows_with_gaps"] = len(rows)

    # Symbols with missing data
    symbols_with_gaps = sorted(set(r["symbol"] for r in rows))
    report["symbols_with_missing_data"] = symbols_with_gaps
    report["symbol_count_with_gaps"] = len(symbols_with_gaps)

    # Most common missing fields
    field_counter = Counter()
    for r in rows:
        fields = _parse_missing_fields(r.get("missing_fields"))
        for f in fields:
            field_counter[f] += 1
    report["most_common_missing_fields"] = [
        {"field": f, "count": c} for f, c in field_counter.most_common(20)
    ]

    # Strategies whose requirements are most often unmet
    strategy_counter = Counter()
    for r in rows:
        strategy_counter[r["strategy_id"]] += 1
    report["strategies_most_unmet"] = [
        {"strategy_id": s, "gap_count": c} for s, c in strategy_counter.most_common(20)
    ]

    # Recommended data refresh actions
    actions = []
    if field_counter:
        top_fields = [f for f, _ in field_counter.most_common(5)]
        actions.append(f"Refresh data pipelines for top missing fields: {', '.join(top_fields)}")
    if symbols_with_gaps:
        sample = symbols_with_gaps[:10]
        actions.append(f"Prioritize data ingestion for symbols: {', '.join(sample)}"
                       + (f" (and {len(symbols_with_gaps) - 10} more)" if len(symbols_with_gaps) > 10 else ""))
    if strategy_counter:
        top_strat = strategy_counter.most_common(1)[0][0]
        actions.append(f"Review data requirements for strategy '{top_strat}' — most frequent gaps")
    if not actions:
        actions.append("No data gaps detected — all requirements met.")
    report["recommended_actions"] = actions

    if verbose:
        report["gap_detail"] = [
            {
                "symbol": r["symbol"],
                "strategy_id": r["strategy_id"],
                "required_data_status": r["required_data_status"],
                "missing_fields": _parse_missing_fields(r.get("missing_fields")),
            }
            for r in rows
        ]

    return report


def _format_md(report):
    lines = [
        "# Strategy-Fit Data Gaps Report",
        "",
        f"**Audit Run ID:** `{report['audit_run_id']}`",
        f"**Generated:** {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"- **Rows with data gaps:** {report['total_rows_with_gaps']}",
        f"- **Symbols affected:** {report['symbol_count_with_gaps']}",
        "",
    ]

    if report["most_common_missing_fields"]:
        lines += [
            "## Most Common Missing Fields",
            "",
            "| Field | Count |",
            "|-------|-------|",
        ]
        for entry in report["most_common_missing_fields"]:
            lines.append(f"| {entry['field']} | {entry['count']} |")
        lines.append("")

    if report["strategies_most_unmet"]:
        lines += [
            "## Strategies With Most Unmet Requirements",
            "",
            "| Strategy | Gap Count |",
            "|----------|-----------|",
        ]
        for entry in report["strategies_most_unmet"]:
            lines.append(f"| {entry['strategy_id']} | {entry['gap_count']} |")
        lines.append("")

    lines += [
        "## Recommended Actions",
        "",
    ]
    for a in report["recommended_actions"]:
        lines.append(f"- {a}")
    lines.append("")

    if report.get("gap_detail"):
        lines += [
            "## Detail (verbose)",
            "",
            "| Symbol | Strategy | Status | Missing Fields |",
            "|--------|----------|--------|----------------|",
        ]
        for d in report["gap_detail"]:
            mf = ", ".join(d["missing_fields"]) if d["missing_fields"] else "-"
            lines.append(f"| {d['symbol']} | {d['strategy_id']} | {d['required_data_status']} | {mf} |")
        lines.append("")

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Strategy-fit data gaps report (read-only)")
    p.add_argument("--latest", action="store_true", help="Use the latest audit_run_id")
    p.add_argument("--output-json", type=str, help="Write JSON report to this path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to this path")
    p.add_argument("--verbose", action="store_true", help="Print detailed gap rows")
    args = p.parse_args()

    if args.latest:
        audit_run_id = _resolve_latest_run_id()
    else:
        audit_run_id = _resolve_latest_run_id()  # default to latest

    if not audit_run_id:
        print("ERROR: No audit_run_id found. Ensure audit data exists.", file=sys.stderr)
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
