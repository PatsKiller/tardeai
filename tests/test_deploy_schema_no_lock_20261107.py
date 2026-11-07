"""LQ-20261107-176 — the deploy schema check must not lock ``deploy_events`` on every upsert.

ANCHOR: DEPLOY_SCHEMA_NO_LOCK_20261107. ``ensure_deploy_tables`` re-executed the whole migration on every
``upsert_deploy_event`` call, i.e. once per detected sale inside ``sync_deploy_events``, whose transaction
stays open across the per-event enrichment. PostgreSQL takes an ACCESS EXCLUSIVE lock on an existing table for
``CREATE TABLE IF NOT EXISTS`` (and a share lock for ``CREATE INDEX IF NOT EXISTS``), so that transaction held
the table out of every reader for the length of the loop. The readers then failed after ``lock_timeout`` with
"canceling statement due to lock timeout" — the reentry desk showed it as "Sell history could not be read."
(witnessed live 2026-11-07T17:18Z: backend 2406101 idle in transaction, ACCESS EXCLUSIVE on deploy_events,
readers waiting behind it).

These tests pin the fix: a catalog lookup, no DDL, when the schema is already there.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deploy_events_db as ded  # noqa: E402

DDL_MARKERS = ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX", "ALTER TABLE",
               "DROP TABLE", "TRUNCATE", "LOCK TABLE")


class _FakeCursor:
    """Records every statement; ``present`` is what the catalog lookup answers."""

    def __init__(self, present: bool):
        self.present = present
        self.executed: list[tuple[str, object]] = []
        self._answer = None

    def execute(self, sql, params=None):
        self._answer = " ".join(str(sql).split())
        self.executed.append((self._answer, params))

    def fetchone(self):
        if "to_regclass" in (self._answer or "").lower():
            return (self.present,)
        return (1,)

    def fetchall(self):
        return []

    def ddl(self) -> list[str]:
        """Every statement that takes a lock on a table — the migration text runs as one statement."""
        return [sql for sql, _ in self.executed if any(m in sql.upper() for m in DDL_MARKERS)]


def test_an_existing_schema_runs_no_ddl_and_takes_no_exclusive_lock():
    cur = _FakeCursor(present=True)
    ded.ensure_deploy_tables(cur)
    assert cur.ddl() == [], "DDL on an existing deploy_events takes ACCESS EXCLUSIVE and blocks every reader"
    assert len(cur.executed) == 1
    sql, params = cur.executed[0]
    assert sql.upper().startswith("SELECT") and "to_regclass" in sql.lower()
    assert tuple(params) == ded.REQUIRED_TABLES


def test_a_missing_schema_still_runs_the_migration():
    cur = _FakeCursor(present=False)
    ded.ensure_deploy_tables(cur)
    ran = [sql for sql, _ in cur.executed if "CREATE TABLE IF NOT EXISTS deploy_events" in sql]
    assert ran, "a first run must still create the tables"
    assert ded.MIGRATION.is_file(), "the migration the check guards must exist"


def test_the_upsert_path_carries_no_ddl_once_the_schema_exists():
    cur = _FakeCursor(present=True)
    ded.upsert_deploy_event(cur, {"event_key": "k1", "symbol": "AAA", "account": "acct", "sold_at": "2026-11-06"})
    assert cur.ddl() == [], "every detected sale re-locked the table for the whole sync transaction"


@pytest.mark.parametrize("answer, expected", [((True,), True), ((False,), False), (None, False), ((None,), False)])
def test_the_catalog_lookup_answers_only_a_clean_true(answer, expected):
    cur = _FakeCursor(present=bool(answer and answer[0]))
    if answer is None or answer == (None,):
        cur.fetchone = lambda: answer
    assert ded._schema_present(cur) is expected


def test_a_migration_that_does_not_exist_does_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(ded, "MIGRATION", tmp_path / "absent.sql")
    cur = _FakeCursor(present=False)
    ded.ensure_deploy_tables(cur)
    assert cur.executed == []
