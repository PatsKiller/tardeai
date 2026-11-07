"""ANCHOR: RETENTION_LOCK_TIMEOUT_20261107 — a nightly batch must not share the interactive 3 s lock guard.

QUALITY ROUND 2, item 1 `platform-maintenance-nightly`. Its receipt reports two failing steps every
night; one of them is `db_retention`:

    ERROR: deploy_plans: canceling statement due to lock timeout
    RETENTION NOT ENFORCED on 1 table(s): deploy_plans
    (2026-10-29, 10-31, 11-02, 11-05, 11-06 — the same table, the same statement)

The trade_ai role carries `lock_timeout=3s`, set by db_adapter.py as the *interactive* anti-cascade
guard. A retention DELETE that waits four seconds behind a writer therefore aborts the whole policy,
and the run exits 1. `deploy_plans` has 0 rows older than its 365-day window, so nothing is deleted
and nothing is at risk — the run loses to a lock only.

Hermetic: fake cursor/connection, no database, no network, no sleeps.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import db_retention as R  # noqa: E402


class LockNotAvailable(Exception):
    """Stands in for psycopg2.errors.LockNotAvailable (SQLSTATE 55P03)."""
    pgcode = "55P03"


class StatementTimeout(Exception):
    """Stands in for psycopg2.errors.QueryCanceled (SQLSTATE 57014)."""
    pgcode = "57014"


class FakeCursor:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0
        self.rowcount = 0

    def execute(self, sql):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        self.rowcount = 7


class FakeConn:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)


# --- classification ---------------------------------------------------------------------------


def test_a_lock_timeout_is_recognised_by_sqlstate():
    assert R._is_lock_timeout(LockNotAvailable("canceling statement due to lock timeout")) is True


def test_a_lock_timeout_is_recognised_by_message_when_no_sqlstate_is_available():
    assert R._is_lock_timeout(Exception("canceling statement due to lock timeout")) is True


def test_a_statement_timeout_is_not_a_lock_timeout():
    """A slow query must not be retried — the retry would rebuild the same work and fail again."""
    assert R._is_lock_timeout(StatementTimeout("canceling statement due to statement timeout")) is False


def test_an_ordinary_error_is_not_a_lock_timeout():
    assert R._is_lock_timeout(Exception('relation "nope" does not exist')) is False


# --- retry ------------------------------------------------------------------------------------


def test_a_transient_lock_is_retried_and_the_delete_succeeds():
    cur, conn = FakeCursor([LockNotAvailable("lock timeout")]), FakeConn()
    count = R._delete_with_retry(cur, conn, "DELETE FROM t", sleep_s=0)
    assert count == 7
    assert cur.calls == 2          # one failure, one success
    assert conn.rollbacks == 1     # the aborted transaction is rolled back before retrying


def test_a_persistent_lock_still_fails_the_policy():
    cur = FakeCursor([LockNotAvailable("lock timeout")] * 3)
    conn = FakeConn()
    with pytest.raises(LockNotAvailable):
        R._delete_with_retry(cur, conn, "DELETE FROM t", attempts=3, sleep_s=0)
    assert cur.calls == 3


def test_a_non_lock_error_is_not_retried():
    boom = RuntimeError("permission denied for table t")
    cur, conn = FakeCursor([boom]), FakeConn()
    with pytest.raises(RuntimeError):
        R._delete_with_retry(cur, conn, "DELETE FROM t", sleep_s=0)
    assert cur.calls == 1
    assert conn.rollbacks == 0


# --- session setting --------------------------------------------------------------------------


def test_the_batch_lock_timeout_is_validated(monkeypatch):
    monkeypatch.setenv("DB_RETENTION_LOCK_TIMEOUT", "120s")
    assert R._batch_lock_timeout() == "120s"
    monkeypatch.setenv("DB_RETENTION_LOCK_TIMEOUT", "5m; DROP TABLE x")
    assert R._batch_lock_timeout() == R.BATCH_LOCK_TIMEOUT
    monkeypatch.delenv("DB_RETENTION_LOCK_TIMEOUT")
    assert R._batch_lock_timeout() == "60s"


def test_the_run_sets_the_batch_lock_timeout_and_deletes_through_the_retry():
    """The setting and the retrying delete must be wired into run(), not merely defined."""
    src = (ROOT / "scripts" / "db_retention.py").read_text()
    assert "SET lock_timeout = '{_batch_lock_timeout()}'" in src
    assert "_delete_with_retry(" in src and "DELETE FROM {table}" in src
