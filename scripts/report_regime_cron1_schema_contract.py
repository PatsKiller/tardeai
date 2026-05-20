#!/usr/bin/env python3
"""report_regime_cron1_schema_contract.py — Verify risk-regime scripts reference real DB columns.

Read-only. No mutations. Prevents AGENT-WORKER-1-style column mismatch bugs.
"""
import argparse, json, re, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

# Scripts to audit
SCRIPTS = [
    ("market_regime_collector.py", ["market_regime_indicators"]),
    ("market_regime_classifier.py", ["market_regime_snapshots", "market_regime_indicators", "risk_regime_run_log"]),
    ("strategy_rotation_engine.py", ["strategy_rotation_signals", "regime_trade_alignment",
                                      "market_regime_snapshots", "strategy_regime_profiles",
                                      "paper_trades", "paper_trade_proposals"]),
    ("strategy_regime_profiler.py", ["strategy_regime_profiles"]),
]

# SQL column reference patterns
SQL_PAT = re.compile(r'(?:SELECT|INSERT\s+INTO|UPDATE|SET|WHERE|AND|OR|ON|VALUES)\s+', re.I)
COL_PAT = re.compile(r'\b([a-z_][a-z0-9_]*)\b', re.I)
# Known SQL keywords to exclude
SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "in", "is", "null", "true", "false",
    "insert", "into", "values", "update", "set", "delete", "create", "table", "index",
    "on", "conflict", "do", "nothing", "limit", "order", "by", "desc", "asc", "as",
    "count", "max", "min", "avg", "sum", "distinct", "now", "interval", "exists",
    "join", "left", "right", "inner", "outer", "group", "having", "between", "like",
    "ilike", "case", "when", "then", "else", "end", "cast", "coalesce", "excluded",
    "primary", "key", "unique", "constraint", "default", "nextval", "serial", "bigint",
    "text", "boolean", "numeric", "jsonb", "timestamp", "integer", "with", "time", "zone",
    "sub", "hours", "days", "returning",
}


def get_table_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute("""SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position""", [table_name])
    return {r[0] for r in cur.fetchall()}


def extract_sql_columns_from_file(filepath):
    """Extract column references from SQL statements in Python file."""
    refs = []
    text = filepath.read_text()
    # Find SQL strings (triple-quoted and single-quoted)
    sql_strings = re.findall(r'"""(.*?)"""', text, re.DOTALL)
    sql_strings += re.findall(r"'''(.*?)'''", text, re.DOTALL)
    # Also single-line SQL in regular strings
    sql_strings += re.findall(r'"((?:SELECT|INSERT|UPDATE|DELETE)\s[^"]*)"', text, re.I)

    for sql in sql_strings:
        # Extract column-like tokens after SQL keywords
        for match in re.finditer(r'(?:SELECT|SET|WHERE|AND|OR)\s+([a-z_][a-z0-9_,\s.=]*)', sql, re.I):
            tokens = re.findall(r'\b([a-z_][a-z0-9_]*)\b', match.group(1), re.I)
            for t in tokens:
                if t.lower() not in SQL_KEYWORDS and len(t) > 1:
                    refs.append(t)
        # INSERT column lists
        for match in re.finditer(r'INSERT\s+INTO\s+\w+\s*\(([^)]+)\)', sql, re.I):
            tokens = re.findall(r'\b([a-z_][a-z0-9_]*)\b', match.group(1), re.I)
            for t in tokens:
                if t.lower() not in SQL_KEYWORDS and len(t) > 1:
                    refs.append(t)
    return list(set(refs))


def main():
    p = argparse.ArgumentParser(description="Risk regime schema contract audit (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)

    # Load all table schemas
    table_cols = {}
    all_tables = set()
    for _, tables in SCRIPTS:
        all_tables.update(tables)
    for t in all_tables:
        table_cols[t] = get_table_columns(conn, t)

    results = []
    mismatches = 0

    for script_name, expected_tables in SCRIPTS:
        script_path = PROJ / "scripts" / script_name
        if not script_path.exists():
            results.append({"script": script_name, "status": "MISSING", "mismatches": []})
            continue

        col_refs = extract_sql_columns_from_file(script_path)
        script_mismatches = []

        for col in col_refs:
            found_in = []
            for table in expected_tables:
                if col in table_cols.get(table, set()):
                    found_in.append(table)

            if not found_in:
                # Could be from a different table or a false positive
                # Check if it exists in ANY of the expected tables
                is_mismatch = True
                # Skip common false positives
                if col in {"mode", "status", "symbol", "id", "type", "value", "signal",
                           "source", "active", "reason", "label", "score", "confidence",
                           "summary", "snapshot", "strategy", "regime", "proposal",
                           "open", "trade", "paper", "test", "pending", "approved"}:
                    is_mismatch = False
                if is_mismatch:
                    script_mismatches.append({
                        "column": col, "expected_tables": expected_tables,
                        "found_in": [], "severity": "warning",
                    })
                    mismatches += 1

        results.append({
            "script": script_name, "status": "OK" if not script_mismatches else "MISMATCH",
            "columns_referenced": len(col_refs), "mismatches": script_mismatches,
        })

    conn.close()

    report = {
        "generated_at": str(Path),
        "total_scripts": len(SCRIPTS),
        "total_mismatches": mismatches,
        "results": results,
    }

    if args.verbose:
        print(f"Schema Contract: {mismatches} mismatches across {len(SCRIPTS)} scripts")
        for r in results:
            status = r["status"]
            print(f"  {r['script']:40s} {status}")
            for m in r.get("mismatches", []):
                print(f"    ! column '{m['column']}' not in {m['expected_tables']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Schema Contract Report\n",
              f"Mismatches: {mismatches}\n",
              "| Script | Status | Columns | Mismatches |",
              "|--------|--------|---------|------------|"]
        for r in results:
            md.append(f"| {r['script']} | {r['status']} | {r.get('columns_referenced', '?')} | {len(r.get('mismatches', []))} |")
        if mismatches:
            md.append("\n## Mismatches")
            for r in results:
                for m in r.get("mismatches", []):
                    md.append(f"- `{r['script']}`: column `{m['column']}` not in {m['expected_tables']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
