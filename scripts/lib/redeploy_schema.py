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


def run_migrations_once(cur, key: str, files) -> None:
    """Execute migration SQL files once per process; cross-connection safe."""
    if key in _done:
        return
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_KEY,))
    for f in files:
        if f.is_file():
            cur.execute(f.read_text())
    _done.add(key)
