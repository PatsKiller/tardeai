"""Serialize + memoize the idempotent redeploy migration DDL.

Per-request ensure-tables ran ALTER TABLE (AccessExclusiveLock, even with IF
NOT EXISTS) on every call; the workstation's parallel initial load fired these
concurrently across handlers and deadlocked Postgres (2026-07-14, relation-level
AccessExclusiveLock cycle). Each migration set now runs at most once per process,
and concurrent first-runners queue on a pg advisory lock instead of deadlocking:
the advisory lock is always acquired before any table lock, so lock order is
globally consistent."""
from __future__ import annotations

_done: set[str] = set()
_ADVISORY_KEY = 0x5245444C  # 'REDL'
_RETRY_AFTER_SEC = 60.0
_next_try: dict[str, float] = {}


def _side_connect():
    """Open a short-lived, autocommit connection for DDL (never the request's own)."""
    import os

    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=10,
        application_name="redeploy_schema_ddl",
    )
    conn.autocommit = True
    return conn


def run_migrations_once(cur, key: str, files, *, connect=None) -> None:
    """Execute migration SQL files once per process, OFF the caller's transaction.

    ALTER TABLE ... IF NOT EXISTS takes ACCESS EXCLUSIVE even when nothing changes,
    and the lock lasts until the transaction ends. Run on the request's cursor, the
    first call after boot left the server's backend idle-in-transaction holding that
    lock on deploy_events (2026-11-07 16:01 ET), starving every later reader. The DDL
    now runs on its own autocommit connection (each statement releases its lock at
    once), serialized by a session advisory lock taken before any table lock. The
    process memo is set only after success; failure is retried after a backoff and
    never raised into the request (the tables exist from earlier boots). `cur` is
    deliberately not used."""
    import time

    if key in _done:
        return
    if time.monotonic() < _next_try.get(key, 0.0):
        return
    conn = None
    try:
        conn = (connect or _side_connect)()
        with conn.cursor() as c:
            c.execute("SET lock_timeout = '5s'")
            c.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_KEY,))
            try:
                for f in files:
                    if f.is_file():
                        c.execute(f.read_text())
            finally:
                c.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_KEY,))
        _done.add(key)
        _next_try.pop(key, None)
    except Exception as exc:  # noqa: BLE001 - schema bootstrap must not break reads
        _next_try[key] = time.monotonic() + _RETRY_AFTER_SEC
        print(f"[redeploy_schema] migration set {key!r} deferred: {type(exc).__name__}: {exc}"[:300])
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
