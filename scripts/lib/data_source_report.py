"""Passive per-source liveness reporting into data_source_health.

Ingestion lanes call report_source() when they actually run, so the health agent's
collect_data_source_health() sees real last_success_at/last_failure_at instead of
'unknown' rows (pre-2026-07-04 only finviz reported, via its probe script).

Uses a DEDICATED autocommit connection — never the caller's db_adapter thread-local
connection, whose open transaction a commit here would silently flush mid-batch.
Success writes are throttled per process; failures always write.
"""
from __future__ import annotations

import os
import time

_conn = None
_last_ok: dict[str, float] = {}
OK_MIN_INTERVAL_S = float(os.getenv("DATA_SOURCE_REPORT_OK_INTERVAL_S", "60"))


def _own_conn():
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn
    import psycopg2
    _conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
        application_name="data_source_report",
    )
    _conn.autocommit = True
    return _conn


def report_source(source_key: str, ok: bool, rows: int | None = None,
                  error: str | None = None) -> None:
    """Record one source run. Never raises; never touches the caller's transaction."""
    global _conn
    try:
        now = time.time()
        if ok and now - _last_ok.get(source_key, 0.0) < OK_MIN_INTERVAL_S:
            return
        cur = _own_conn().cursor()
        if ok:
            cur.execute(
                """UPDATE data_source_health
                   SET status='healthy', last_success_at=NOW(),
                       last_row_count=COALESCE(%s, last_row_count),
                       failure_count=0, degraded=false, last_error=NULL, updated_at=NOW()
                   WHERE source_key=%s""",
                (rows, source_key))
            _last_ok[source_key] = now
        else:
            cur.execute(
                """UPDATE data_source_health
                   SET status='error', last_failure_at=NOW(),
                       failure_count=failure_count+1, degraded=true,
                       last_error=%s, updated_at=NOW()
                   WHERE source_key=%s""",
                ((error or "")[:200], source_key))
    except Exception:
        try:
            if _conn is not None:
                _conn.close()
        except Exception:
            pass
        _conn = None
