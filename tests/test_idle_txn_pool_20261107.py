"""ANCHOR: IDLE_TXN_POOL_20261107 — the fan-out pools hand their worker's DB transaction back.

`/v3/health` reported 160 Postgres idle-in-transaction kills in 3 h (588 on 11-06). Read-only
`pg_stat_activity` sampling on 2026-11-07 attributed them:

* 14 of 19 backends that sat ``idle in transaction`` in a 6-minute window belonged to
  `portfolio_server.py`; two were sampled at xact age 117.4 s / 117.5 s (pids 652988 and 653000)
  and PostgreSQL logs both killed at the 120 s role timeout — the sampler saw them alive.
* Their last statements were `list_deploy_events` (the `deploy` probe) and
  `watch_domains._positions_store_rows` (the `held` probe) — exactly the two DB probes of one
  `/api/v2/home/do-now` build.

`lib/data_broker/home_do_now.build` fans its probes out onto a module-level
`ThreadPoolExecutor(max_workers=8)` whose workers live for the life of the server process, and
`db_adapter._get_conn()` gives every thread its own connection with ``autocommit = False``. A read
probe never commits, so after the probe the worker thread idles with an open transaction; 120 s
later PostgreSQL kills the backend. `lib/needs_action.aggregate` has the same shape (16 workers).
`watch_domains._db_query` is the shared read helper that never ended its transaction.

The fix has three parts, each with a pair here — the positive (the transaction is ended) and a
control (nothing is ended when there is nothing to end, and a probe that raises still releases):

* `db_adapter.end_thread_txn()` — roll back an open transaction, keep the connection.
* `watch_domains._db_query` — commit on success, roll back on failure.
* `home_do_now.build` / `needs_action.aggregate` — submit every probe through a wrapper that
  calls `end_thread_txn()` in a ``finally``.

Hermetic: fake connections and a recording executor. No database, no pool, no host state.

COVERS: scripts/db_adapter.py::end_thread_txn
COVERS: scripts/lib/data_broker/watch_domains.py::_db_query
COVERS: scripts/lib/data_broker/home_do_now.py::_probe
COVERS: scripts/lib/data_broker/home_do_now.py::build
COVERS: scripts/lib/needs_action.py::_probe
COVERS: scripts/lib/needs_action.py::aggregate
"""
from __future__ import annotations

import concurrent.futures as cf

import psycopg2.extensions as pgext
import pytest

import db_adapter as A
from scripts.lib import needs_action as NA
from scripts.lib.data_broker import home_do_now as HDN
from scripts.lib.data_broker import watch_domains as WD


class _FakeCursor:
    """Cursor that records execute()/close() and answers the configured rows."""

    def __init__(self, rows, *, raises=None):
        self.rows = rows
        self.raises = raises
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def execute(self, sql, params=()):
        if self.raises is not None:
            raise self.raises
        self.sql, self.params = sql, params

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _FakeConn:
    """The slice of a psycopg2 connection db_adapter/read helpers touch."""

    def __init__(self, *, status=None, closed=0, rows=(), raises=None):
        self._status = pgext.TRANSACTION_STATUS_IDLE if status is None else status
        self.closed = closed
        self.calls: list[str] = []
        self.rows = list(rows)
        self.raises = raises

    def get_transaction_status(self):
        return self._status

    def rollback(self):
        self.calls.append("rollback")

    def commit(self):
        self.calls.append("commit")
        if self.raises is not None:
            # a real connection whose statement failed is INERROR: COMMIT raises InFailedSqlTransaction
            raise self.raises

    def cursor(self):
        return _FakeCursor(self.rows, raises=self.raises)

    def close(self):
        self.calls.append("close")


@pytest.fixture
def thread_conn(monkeypatch):
    """Replace THIS thread's db_adapter connection; restore it afterwards."""

    def _set(conn):
        monkeypatch.setattr(A._tls, "conn", conn, raising=False)
        return conn

    return _set


class _RecordingExecutor:
    """Executor that records what was submitted and completes it inline."""

    def __init__(self):
        self.submitted: list[tuple] = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))
        fut = cf.Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 — surfaced through the future, as a real executor does
            fut.set_exception(exc)
        return fut


# ── end_thread_txn ───────────────────────────────────────────────────────────────────────────────────


def test_end_thread_txn_rolls_back_an_open_transaction(thread_conn):
    conn = thread_conn(_FakeConn(status=pgext.TRANSACTION_STATUS_INTRANS))
    assert A.end_thread_txn() is True
    assert conn.calls == ["rollback"]


def test_end_thread_txn_rolls_back_an_aborted_transaction(thread_conn):
    conn = thread_conn(_FakeConn(status=pgext.TRANSACTION_STATUS_INERROR))
    assert A.end_thread_txn() is True
    assert conn.calls == ["rollback"]


def test_end_thread_txn_leaves_an_idle_connection_alone(thread_conn):
    """Control: a committed (idle) connection must not be touched — no wasted round trip per probe."""
    conn = thread_conn(_FakeConn(status=pgext.TRANSACTION_STATUS_IDLE))
    assert A.end_thread_txn() is False
    assert conn.calls == []


def test_end_thread_txn_ignores_a_closed_connection(thread_conn):
    """Control: a connection the server already killed reads as closed and is not rolled back."""
    conn = thread_conn(_FakeConn(status=pgext.TRANSACTION_STATUS_INTRANS, closed=1))
    assert A.end_thread_txn() is False
    assert conn.calls == []


def test_end_thread_txn_has_nothing_to_do_without_a_connection(thread_conn):
    thread_conn(None)
    assert A.end_thread_txn() is False


# ── watch_domains._db_query ─────────────────────────────────────────────────────────────────────────


def test_watch_domains_db_query_commits_its_read(monkeypatch):
    conn = _FakeConn(rows=[(1, "ANET")])
    monkeypatch.setattr(A, "_get_conn", lambda: conn)
    assert WD._db_query("SELECT 1", fetch="all") == [(1, "ANET")]
    assert conn.calls == ["commit"], "the read must not leave the worker idle in transaction"


def test_watch_domains_db_query_fetch_one_also_commits(monkeypatch):
    conn = _FakeConn(rows=[(7,)])
    monkeypatch.setattr(A, "_get_conn", lambda: conn)
    assert WD._db_query("SELECT 7", fetch="one") == (7,)
    assert conn.calls == ["commit"]


def test_watch_domains_db_query_rolls_back_a_failed_read(monkeypatch):
    conn = _FakeConn(raises=RuntimeError("boom"))
    monkeypatch.setattr(A, "_get_conn", lambda: conn)
    with pytest.raises(RuntimeError):
        WD._db_query("SELECT nope")
    assert conn.calls == ["commit", "rollback"], "a failed statement must not stay open either"


# ── the pool wrappers ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("module", [HDN, NA])
def test_probe_releases_the_transaction_after_the_probe(module, thread_conn):
    conn = thread_conn(_FakeConn(status=pgext.TRANSACTION_STATUS_INTRANS))
    assert module._probe(lambda: "value") == "value"
    assert conn.calls == ["rollback"]


@pytest.mark.parametrize("module", [HDN, NA])
def test_probe_releases_the_transaction_when_the_probe_raises(module, thread_conn):
    conn = thread_conn(_FakeConn(status=pgext.TRANSACTION_STATUS_INTRANS))
    with pytest.raises(ValueError):
        module._probe(lambda: (_ for _ in ()).throw(ValueError("probe failed")))
    assert conn.calls == ["rollback"], "a raising probe must not leak its transaction either"


def test_home_do_now_build_submits_every_probe_through_the_wrapper():
    ex = _RecordingExecutor()
    HDN.build({"probe_a": lambda: 1, "probe_b": lambda: 2}, executor=ex)
    assert [call[0] for call in ex.submitted] == [HDN._probe, HDN._probe]


def test_needs_action_aggregate_submits_every_probe_through_the_wrapper():
    ex = _RecordingExecutor()
    NA.aggregate(
        {"probe_a": lambda: 1},
        rules={"probe_a": lambda payload, now: []},
        executor=ex,
    )
    assert [call[0] for call in ex.submitted] == [NA._probe]
