#!/usr/bin/env python3
"""report_attr1_benchmark_alpha.py — Report attribution/benchmark table presence and data health.

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

ATTRIBUTION_TABLE_PATTERNS = [
    "attribution",
    "benchmark",
    "alpha",
    "performance_attribution",
]


def run_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables_found": [],
        "data_present": False,
        "row_counts": {},
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

        # Find any attribution/benchmark related tables
        like_clauses = " OR ".join(
            f"table_name LIKE '%{p}%'" for p in ATTRIBUTION_TABLE_PATTERNS
        )
        cur.execute(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = 'public' AND ({like_clauses})"
        )
        report["tables_found"] = [row[0] for row in cur.fetchall()]

        if not report["tables_found"]:
            report["root_cause"] = "no_benchmark_tables"
            report["recommended_fix"] = (
                "create attribution/benchmark tables; "
                "run the performance attribution pipeline to populate"
            )
            cur.close()
            if verbose:
                _print_report(report)
            return report

        # Check each table for data
        for table in report["tables_found"]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                report["row_counts"][table] = count
                if count > 0:
                    report["data_present"] = True
            except Exception:
                report["row_counts"][table] = None
                conn.rollback()

        cur.close()
    except Exception as e:
        report["root_cause"] = f"query_error: {e}"
        conn.rollback()

    # --- Root cause ---
    if report["root_cause"] is None:
        if not report["data_present"]:
            empty_tables = [t for t, c in report["row_counts"].items() if c == 0]
            report["root_cause"] = (
                f"tables exist but empty: {', '.join(empty_tables)}"
            )
            report["recommended_fix"] = "run attribution pipeline to populate tables"
        else:
            report["root_cause"] = "none — attribution tables exist with data"
            report["recommended_fix"] = "none"

    if verbose:
        _print_report(report)

    return report


def _print_report(report):
    print("=== Attribution Benchmark Alpha Report ===")
    print(f"  Tables found: {report['tables_found']}")
    print(f"  Data present: {report['data_present']}")
    print(f"  Row counts: {report['row_counts']}")
    print(f"  Root cause: {report['root_cause']}")
    print(f"  Fix: {report['recommended_fix']}")


def main():
    p = argparse.ArgumentParser(description="Attribution benchmark alpha report (read-only)")
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
            "# Attribution Benchmark Alpha Report",
            f"Generated: {report['generated_at']}",
            "",
            "## Tables Found",
        ]
        if report["tables_found"]:
            for t in report["tables_found"]:
                count = report["row_counts"].get(t, "?")
                lines.append(f"- `{t}`: {count} rows")
        else:
            lines.append("- None found")
        lines.append(f"\n## Data Present\n- {report['data_present']}")
        lines.append(f"\n## Root Cause\n- {report['root_cause'] or 'none'}")
        lines.append(f"\n## Recommended Fix\n- {report['recommended_fix'] or 'none'}")
        Path(args.output_md).write_text("\n".join(lines))
        print(f"Markdown written to {args.output_md}")


if __name__ == "__main__":
    main()
