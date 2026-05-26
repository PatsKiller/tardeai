# Source Export: scripts/screener_run_health.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/screener_run_health.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `35342f997f091ccc8696ba3c6a6bf91e7cbf270c9e0230c4034969884a6a047e` |
| **File Size** | 5851 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""screener_run_health.py — Track and classify screener run health.

Records run completeness into screener_run_health table and provides
classification functions for pipeline orchestration.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def classify_run_health(stats: dict) -> tuple:
    """Classify run health from stats dict.
    Returns (status, reason_codes).
    """
    reasons = []
    symbols = stats.get("symbols_scanned", 0)
    expected_min = stats.get("expected_min_symbols", 40)
    raw_rows = stats.get("raw_rows", 0)

    if stats.get("error"):
        reasons.append(stats["error"])
        return "RUN_FAILED", reasons

    if symbols == 0 and raw_rows == 0:
        reasons.append("CSV_EMPTY")
        return "RUN_FAILED", reasons

    if symbols >= expected_min:
        return "RUN_HEALTHY", reasons

    if symbols >= 25:
        if raw_rows > 0 and symbols < raw_rows * 0.5:
            reasons.append("DEDUP_TOO_AGGRESSIVE")
        if stats.get("screener_count", 0) <= 1:
            reasons.append("ONLY_ONE_SCREENER_RETURNED")
        return "RUN_PARTIAL", reasons

    # Under 25
    if stats.get("auth_failed"):
        reasons.append("FINVIZ_AUTH_FAILED")
    elif not stats.get("has_cookie"):
        reasons.append("FINVIZ_AUTH_MISSING")
    if raw_rows <= 10:
        reasons.append("ROW_LIMIT_10_DETECTED")
    if stats.get("screener_count", 0) <= 1:
        reasons.append("ONLY_ONE_SCREENER_RETURNED")
    if stats.get("parse_error"):
        reasons.append("PARSE_ERROR")
    if stats.get("timeout"):
        reasons.append("PROVIDER_TIMEOUT")
    if not reasons:
        reasons.append("UNIVERSE_TOO_SMALL")
    return "RUN_UNDERFILLED", reasons


def record_screener_run_start(conn, run_label: str, source: str = "finviz",
                               expected_min_symbols: int = 40):
    """Record the start of a screener run. Returns the row id."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO screener_run_health
            (run_label, run_date, source, expected_min_symbols, status, started_at)
        VALUES (%s, CURRENT_DATE, %s, %s, 'RUNNING', NOW())
        RETURNING id
    """, [run_label, source, expected_min_symbols])
    row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def record_screener_run_finish(conn, run_label: str, stats: dict):
    """Record the completion of a screener run."""
    status, reason_codes = classify_run_health(stats)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO screener_run_health
            (run_label, run_date, source, expected_min_symbols, target_symbols,
             symbols_scanned, go_count, wait_count, no_go_count,
             raw_rows, normalized_rows, deduped_symbols,
             status, reason_codes, input_snapshot, output_snapshot, finished_at)
        VALUES (%s, CURRENT_DATE, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, NOW())
    """, [
        run_label,
        stats.get("source", "finviz"),
        stats.get("expected_min_symbols", 40),
        stats.get("target_symbols", 60),
        stats.get("symbols_scanned", 0),
        stats.get("go_count", 0),
        stats.get("wait_count", 0),
        stats.get("no_go_count", 0),
        stats.get("raw_rows", 0),
        stats.get("normalized_rows", 0),
        stats.get("deduped_symbols", 0),
        status,
        json.dumps(reason_codes),
        json.dumps(stats.get("input_snapshot")) if stats.get("input_snapshot") else None,
        json.dumps(stats.get("output_snapshot")) if stats.get("output_snapshot") else None,
    ])
    conn.commit()
    return {"status": status, "reason_codes": reason_codes}


def get_latest_run_health(conn, run_date=None):
    """Get the latest run health record for a given date (default today)."""
    cur = conn.cursor()
    if run_date:
        cur.execute("""
            SELECT id, run_label, run_date, symbols_scanned, go_count, wait_count,
                   no_go_count, status, reason_codes, finished_at,
                   expected_min_symbols, target_symbols
            FROM screener_run_health
            WHERE run_date = %s
            ORDER BY finished_at DESC NULLS LAST
            LIMIT 1
        """, [run_date])
    else:
        cur.execute("""
            SELECT id, run_label, run_date, symbols_scanned, go_count, wait_count,
                   no_go_count, status, reason_codes, finished_at,
                   expected_min_symbols, target_symbols
            FROM screener_run_health
            WHERE run_date = CURRENT_DATE
            ORDER BY finished_at DESC NULLS LAST
            LIMIT 1
        """)
    row = cur.fetchone()
    if not row:
        return None
    cols = ["id", "run_label", "run_date", "symbols_scanned", "go_count", "wait_count",
            "no_go_count", "status", "reason_codes", "finished_at",
            "expected_min_symbols", "target_symbols"]
    return dict(zip(cols, row))


if __name__ == "__main__":
    conn = get_conn()
    health = get_latest_run_health(conn)
    if health:
        print(json.dumps(health, indent=2, default=str))
    else:
        print("No run health records for today")
    conn.close()
```
