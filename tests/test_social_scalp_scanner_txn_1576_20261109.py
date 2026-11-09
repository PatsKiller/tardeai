#!/usr/bin/env python3
"""LQ-20261107-1576 (P0): no Postgres transaction may span this lane's network work.

Role ``trade_ai`` carries ``idle_in_transaction_session_timeout = 120s``. The 09:30 ET run on
2026-11-09 read social posts (which, in driver-managed transaction mode, opens a transaction),
spent ~2 minutes enriching on Finviz, and then died writing the routed job:

    psycopg2.OperationalError: SSL connection has been closed unexpectedly
      scripts/lib/agent_job_queue.py:69  insert_agent_job_unless_pending -> cur.execute

The fake connection below enforces the server's rule: a statement issued while a transaction has
been idle for longer than the timeout raises exactly that error. With ``autocommit`` no statement
leaves a transaction open, so the same sequence completes; the reconnect backstop covers a socket
that is dropped for any other reason.

Fail-before: ``test_no_transaction_is_left_open_across_the_finviz_phase`` drives the real
``run_scan`` through a connection with driver-managed transactions (the pre-fix state) and gets
the live failure. Hermetic: no database, no network, synthetic rows only.
"""
import os
import sys

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import social_scalp_scanner as scanner  # noqa: E402

IDLE_LIMIT_S = 120.0  # the live role's idle_in_transaction_session_timeout
SSL_CLOSED = "SSL connection has been closed unexpectedly"
SYMBOL = "SYNX"


class FakeServer:
    """Virtual clock plus the server-side rule that killed the 09:30 ET run."""

    def __init__(self):
        self.now = 0.0
        self.killed = 0

    def advance(self, seconds):
        self.now += seconds


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.begin_statement()
        self.conn.statements.append(" ".join(sql.split())[:70])
        self._rows = _scripted_result(sql)
        self.conn.end_statement()

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


def _scripted_result(sql):
    if "watchlist_agent_jobs" in sql:
        return [(1,)]  # the guarded insert landed a row
    if "FROM social_posts" in sql:
        return [
            {
                "platform": "stocktwits",
                "symbols_mentioned": [SYMBOL],
                "sentiment": "bullish",
                "text": "synthetic post for the transaction test",
                "post_date": None,
                "strategy_tags": [],
            }
        ]
    return []


class FakeConn:
    """Enough of psycopg2's connection to model an idle-in-transaction kill.

    ``honour_autocommit=False`` models the pre-fix state, where the scanner had no such switch:
    the assignment is accepted and transactions are still driver-managed.
    """

    def __init__(self, server, honour_autocommit=True):
        self.server = server
        self.honour_autocommit = honour_autocommit
        self._autocommit = False
        self.txn_idle_since = None
        self.closed = False
        self.statements = []

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._autocommit = bool(value) and self.honour_autocommit

    def begin_statement(self):
        if self.closed:
            raise psycopg2.OperationalError("connection already closed")
        if self._autocommit:
            return
        if self.txn_idle_since is not None and self.server.now - self.txn_idle_since >= IDLE_LIMIT_S:
            self.closed = True
            self.server.killed += 1
            raise psycopg2.OperationalError(SSL_CLOSED)
        if self.txn_idle_since is None:
            self.txn_idle_since = self.server.now

    def end_statement(self):
        if not self._autocommit and self.txn_idle_since is not None:
            self.txn_idle_since = self.server.now

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def commit(self):
        self.txn_idle_since = None

    def rollback(self):
        self.txn_idle_since = None

    def close(self):
        self.closed = True


class FakeDB:
    def __init__(self, server, honour_autocommit=True):
        self.server = server
        self.honour_autocommit = honour_autocommit
        self.connections = []

    def connect(self):
        conn = FakeConn(self.server, self.honour_autocommit)
        self.connections.append(conn)
        return conn


def _wire(monkeypatch, *, honour_autocommit=True):
    """Point the real run_scan at a fake server and synthetic Finviz data."""
    server = FakeServer()
    db = FakeDB(server, honour_autocommit)

    def _base_data(symbols):
        # $174 is above SKIP_IF_PRICE_ABOVE, so the symbol routes to portfolio agents — the
        # statement the 09:30 ET run died on.
        return {s: {"price": 174.13, "change_pct": 1.0, "volume": 1000} for s in symbols}

    def _enrich(symbols, project_root=None):
        server.advance(IDLE_LIMIT_S + 2)  # the live run spent ~121 s in Finviz enrichment
        return {s: {"rvol": 1.2, "float_m": 12.0} for s in symbols}

    # Patch the driver, not get_db: get_db() must still run so its autocommit switch is what is
    # being exercised.
    monkeypatch.setattr(scanner.psycopg2, "connect", lambda *args, **kwargs: db.connect())
    monkeypatch.setattr(scanner, "MIN_MENTIONS", 1)
    monkeypatch.setattr(scanner, "fetch_finviz_base", _base_data)
    monkeypatch.setattr(scanner, "enrich_tickers", _enrich)
    monkeypatch.setattr(scanner, "_load_weights", lambda root: {})
    return server, db


def test_no_transaction_is_left_open_across_the_finviz_phase(monkeypatch):
    """PASS after the fix, FAIL before it: the server never has to kill an idle transaction."""
    server, db = _wire(monkeypatch, honour_autocommit=True)

    scanner.run_scan()

    assert server.killed == 0, "a transaction was left idle long enough for the server to kill it"
    assert any("watchlist_agent_jobs" in s for s in db.connections[0].statements), "the routed job never reached the queue"


def test_the_backstop_reconnects_once_when_the_socket_is_still_dropped(monkeypatch):
    """A drop for any other reason (here: driver-managed transactions) costs one reconnect, not the run."""
    server, db = _wire(monkeypatch, honour_autocommit=False)

    scanner.run_scan()

    assert server.killed == 1
    assert len(db.connections) == 2, "the run must reconnect exactly once, not loop"
    assert any("watchlist_agent_jobs" in s for s in db.connections[-1].statements)


def test_the_fake_enforces_the_server_rule_that_killed_the_live_run():
    """The harness itself is faithful: SELECT, 121 s of network work, then INSERT -> the live error."""
    server = FakeServer()
    conn = FakeConn(server)

    cur = conn.cursor()
    cur.execute("SELECT platform FROM social_posts")
    server.advance(IDLE_LIMIT_S + 1)

    with pytest.raises(psycopg2.OperationalError, match="SSL connection has been closed"):
        conn.cursor().execute("INSERT INTO watchlist_agent_jobs (id) SELECT %s WHERE NOT EXISTS (SELECT 1)")

    assert server.killed == 1
