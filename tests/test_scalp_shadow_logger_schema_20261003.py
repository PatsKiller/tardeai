"""The shadow ignition engine must not take a table lock on every run.

2026-09-17 → 2026-10-03: ensure_schema re-ran ADD COLUMN DDL every 5 minutes, hit the lock
timeout, and the engine wrote no ignition rows for 16 days (no TRIGGER fires, no moomoo L2 arm).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_shadow_logger as ssl  # noqa: E402


class _Cur:
    def __init__(self, present: bool):
        self.present, self.executed = present, []

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchone(self):
        return (1,) if self.present else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, present: bool):
        self.cur = _Cur(present)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def test_existing_schema_runs_no_ddl():
    conn = _Conn(present=True)
    ssl.ensure_schema(conn)
    assert len(conn.cur.executed) == 1 and "information_schema" in conn.cur.executed[0]
    assert not any("ALTER TABLE" in s or "CREATE TABLE" in s for s in conn.cur.executed)


def test_missing_schema_still_migrates():
    conn = _Conn(present=False)
    ssl.ensure_schema(conn)
    assert any("CREATE TABLE" in s for s in conn.cur.executed)
    assert any("ALTER TABLE" in s for s in conn.cur.executed)
