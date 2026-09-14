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


_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
_warned = False


def _db_setting(key: str, default: str = "") -> str:
    """os.environ first, then the project .env (names only are read, never printed).

    2026-09-14: cron runs ``external_market_data_ingest.py --fundamentals``
    without sourcing .env. The script's own writes read .env directly and
    succeeded, but this connection had no DB_PASSWORD, failed inside the
    swallowed exception, and alpha_vantage's health row stayed 'unknown' from
    2026-05-09 while the lane ran every Monday.
    """
    val = os.getenv(key, "")
    if val:
        return val
    try:
        with open(_ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return default


def _own_conn():
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn
    import psycopg2
    _conn = psycopg2.connect(
        host=_db_setting("DB_HOST", "localhost"),
        port=int(_db_setting("DB_PORT", "5432")),
        dbname=_db_setting("DB_NAME", "trade_ai"),
        user=_db_setting("DB_USER", "trade_ai"),
        password=_db_setting("DB_PASSWORD", ""),
        connect_timeout=5,
        application_name="data_source_report",
    )
    _conn.autocommit = True
    return _conn


def report_source(source_key: str, ok: bool, rows: int | None = None,
                  error: str | None = None) -> None:
    """Record one source run. Never raises; never touches the caller's transaction.

    DATA_SOURCE_REPORT_DISABLED=1 makes this a no-op -- for dry runs and for any
    process that must not write the ledger (a CI runner, a worktree test).
    """
    global _conn
    if os.getenv("DATA_SOURCE_REPORT_DISABLED", "") == "1":
        return
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
    except Exception as exc:
        global _warned
        if not _warned:
            # Never raises, but never silent either: a lane whose health cannot be
            # recorded reads "unknown" forever (alpha_vantage, 2026-05-09..09-14).
            import sys
            print(f"[data_source_report] could not record {source_key}: {type(exc).__name__}", file=sys.stderr)
            _warned = True
        try:
            if _conn is not None:
                _conn.close()
        except Exception:
            pass
        _conn = None
