# Source Export: scripts/backtest_dataset_builder.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/backtest_dataset_builder.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `b91455543d4f756e644b51ad1be674fc651139df37b1ea5267d921b5d8b5880f` |
| **File Size** | 4854 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""backtest_dataset_builder.py — Build reusable backtest datasets from local DB sources.

Usage:
    .venv/bin/python scripts/backtest_dataset_builder.py --list-sources --json
    .venv/bin/python scripts/backtest_dataset_builder.py --build --source trade_ai_scans --dry-run --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="DS_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()

SOURCES = {
    "trade_ai_scans": {"table": "trade_ai_scans", "date_col": "scanned_at", "symbol_col": "symbol"},
    "paper_trades": {"table": "paper_trades", "date_col": "created_at", "symbol_col": "symbol"},
    "paper_proposals": {"table": "paper_trade_proposals", "date_col": "created_at", "symbol_col": "symbol"},
}

def list_sources(conn):
    results = []
    cur = conn.cursor()
    for name, cfg in SOURCES.items():
        try:
            cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT {cfg['symbol_col']}), MIN({cfg['date_col']}), MAX({cfg['date_col']}) FROM {cfg['table']}")
            row = cur.fetchone()
            results.append({"source": name, "table": cfg["table"], "rows": row[0],
                           "symbols": row[1], "start": str(row[2]), "end": str(row[3])})
        except Exception:
            results.append({"source": name, "error": "table not available"})
            conn.rollback()
    return results

def build_dataset(conn, source_name, dry_run=True):
    if source_name not in SOURCES:
        return {"error": f"Unknown source: {source_name}"}
    cfg = SOURCES[source_name]
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT {cfg['symbol_col']}), MIN({cfg['date_col']}), MAX({cfg['date_col']}) FROM {cfg['table']}")
    row = cur.fetchone()
    symbols = []
    cur.execute(f"SELECT DISTINCT {cfg['symbol_col']} FROM {cfg['table']} WHERE {cfg['symbol_col']} IS NOT NULL ORDER BY 1")
    symbols = [r[0] for r in cur.fetchall()]

    dataset = {
        "dataset_id": _uid(), "name": f"{source_name}_full",
        "source_type": source_name, "symbols": symbols[:500],
        "start_date": str(row[2].date()) if row[2] else None,
        "end_date": str(row[3].date()) if row[3] else None,
        "bar_interval": "mixed", "rows_count": row[0],
        "missing_data_notes": "No OHLCV — uses scan price snapshots only",
        "assumptions": {"no_intrabar_data": True, "price_at_scan_time_only": True},
    }
    if not dry_run:
        cur.execute("""
            INSERT INTO backtest_datasets (dataset_id, name, source_type, symbols, start_date, end_date,
                bar_interval, rows_count, missing_data_notes, assumptions)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dataset_id) DO NOTHING
        """, [dataset["dataset_id"], dataset["name"], dataset["source_type"],
              json.dumps(dataset["symbols"]), dataset["start_date"], dataset["end_date"],
              dataset["bar_interval"], dataset["rows_count"], dataset["missing_data_notes"],
              json.dumps(dataset["assumptions"])])
        conn.commit()
    return dataset

def main():
    parser = argparse.ArgumentParser(description="Backtest Dataset Builder")
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--source", default="trade_ai_scans")
    parser.add_argument("--dataset-id")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = _get_conn()
    try:
        if args.list_sources:
            sources = list_sources(conn)
            print(json.dumps(sources, indent=2, default=str) if args.json else str(sources))
        elif args.build:
            ds = build_dataset(conn, args.source, dry_run=args.dry_run)
            out = {"mode": "dry_run" if args.dry_run else "applied", "dataset": ds}
            print(json.dumps(out, indent=2, default=str) if args.json else str(out))
        elif args.dataset_id and args.summary:
            cur = conn.cursor()
            cur.execute("SELECT * FROM backtest_datasets WHERE dataset_id=%s", [args.dataset_id])
            row = cur.fetchone()
            print(json.dumps({"found": bool(row)}, indent=2) if args.json else str(row))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
```
