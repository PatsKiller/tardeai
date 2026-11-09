#!/usr/bin/env python3
"""LQ-20261107-1576 (P0): the backfill's read transaction must not span the extraction loop.

Role ``trade_ai`` carries ``idle_in_transaction_session_timeout = 120s``. On 2026-11-09 the hourly
``document-mentions-backfill`` slot opened a Postgres session at 09:25:13 and the server terminated
it at 09:27:14 ("terminating connection due to idle-in-transaction timeout"); the 08:25 slot died the
same way. The cause is structural, not a slow query: psycopg2 keeps the batch ``SELECT``'s
transaction open until a commit, and the extraction loop below it writes nothing for documents it
cannot decide (``no_mention`` / ``undecided`` rows never reach ``persist()``), so the transaction can
sit open for minutes while the process is client-side busy.

The fake connection below enforces the server's rule: a statement issued while a transaction has been
idle for longer than the timeout raises the error the live lane would see. The fake exposes no
``autocommit`` (it is a driver-managed connection, like ``_conn()``), so the only way the run can
survive the 121 s extraction is the commit that ends the read transaction before the loop starts.

Fail-before: with ``scripts/backfill_document_mentions.py`` at its pre-fix form the first test dies
with ``psycopg2.OperationalError`` from the writer's INSERT. Hermetic: no database, no network.
"""
import os
import sys

import psycopg2
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import backfill_document_mentions as bfill  # noqa: E402
import scripts.lib.document_mention_matcher as matcher  # noqa: E402

IDLE_LIMIT_S = 120.0  # the live role's idle_in_transaction_session_timeout
SSL_CLOSED = "SSL connection has been closed unexpectedly"
TABLE = "news_articles"
DOC_ID = 101


class FakeServer:
    """Virtual clock plus the server-side rule that killed the 08:25 and 09:25 backfill slots."""

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
    if f"FROM {TABLE}" in sql:
        return [(DOC_ID, "SYNX", "synthetic prose for the transaction test")]
    if "document_mentions" in sql:  # the writer's INSERT ... RETURNING id
        return [(7,)]
    return []


class FakeConn:
    """Enough of psycopg2's connection to model an idle-in-transaction kill.

    No ``autocommit`` attribute: this models ``_conn()``, which returns a plain driver-managed
    connection. A transaction opens on the first statement and stays open until ``commit()``.
    """

    def __init__(self, server):
        self.server = server
        self.txn_idle_since = None
        self.closed = False
        self.statements = []

    def begin_statement(self):
        if self.closed:
            raise psycopg2.OperationalError("connection already closed")
        if self.txn_idle_since is not None and self.server.now - self.txn_idle_since >= IDLE_LIMIT_S:
            self.closed = True
            self.server.killed += 1
            raise psycopg2.OperationalError(SSL_CLOSED)
        if self.txn_idle_since is None:
            self.txn_idle_since = self.server.now

    def end_statement(self):
        if self.txn_idle_since is not None:
            self.txn_idle_since = self.server.now

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def commit(self):
        self.txn_idle_since = None

    def rollback(self):
        self.txn_idle_since = None

    def close(self):
        self.closed = True


def _wire(monkeypatch):
    """Drive the real ``run()`` over a fake connection and a 121 s synthetic extraction."""
    server = FakeServer()
    conn = FakeConn(server)
    written = []

    def _match(text, names=None, own_symbol=None):
        server.advance(IDLE_LIMIT_S + 2)  # the live slot spent minutes extracting before any write
        return [{
            "symbol": "SYNX",
            "subject_guid": "synthetic-subject-guid",
            "issuer_guid": None,
            "identity_status": "resolved",
            "role": "subject",
            "role_source": "deterministic",
            "role_confidence": 1.0,
            "matched_via": "symbol",
            "matched_text": "SYNX",
        }]

    def _writer(c, *, source_table, source_id, rows):
        cur = c.cursor()
        cur.execute("INSERT INTO document_mentions (id) VALUES (%s) RETURNING id")  # crosses the server rule
        c.commit()
        written.append((source_table, source_id))
        return len(rows)

    monkeypatch.setattr(matcher, "match_mentions", _match)
    return server, conn, written, _writer


def _run(conn, writer):
    return bfill.run(TABLE, 500, True, mark=0, names={"Synthetic Corp": ["SYNX"]},
                     conn=conn, registry={}, persist_fn=writer)


def test_no_transaction_spans_the_extraction_loop(monkeypatch):
    """PASS after the fix, FAIL before it: the read transaction is closed before the loop starts."""
    server, conn, written, writer = _wire(monkeypatch)

    stat = _run(conn, writer)

    assert server.killed == 0, "a transaction was left idle long enough for the server to kill it"
    assert written == [(TABLE, DOC_ID)], "the decided mention never reached the writer"
    assert stat["written"] == 1


def test_the_loop_writes_nothing_for_undecidable_documents_and_still_survives(monkeypatch):
    """The live shape: the loop extracts and writes nothing, then the connection is reused."""
    server, conn, written, writer = _wire(monkeypatch)
    monkeypatch.setattr(matcher, "match_mentions", lambda text, names=None, own_symbol=None: (
        server.advance(IDLE_LIMIT_S + 2) or []))

    stat = _run(conn, writer)

    # No mention -> no write -> the pre-fix transaction would be open and idle for the whole loop.
    assert written == []
    assert stat["no_mention"] == 1
    assert server.killed == 0


def test_the_harness_enforces_the_server_rule_that_killed_the_live_slots():
    """The fake is faithful without the commit: SELECT, 121 s of work, INSERT -> the live kill."""
    server = FakeServer()
    conn = FakeConn(server)

    conn.cursor().execute(f"SELECT id FROM {TABLE}")  # nosemgrep: tq-py-sql-fstring -- the fake connection parses nothing; TABLE is a constant here and no database is opened
    server.advance(IDLE_LIMIT_S + 1)

    with pytest.raises(psycopg2.OperationalError, match="SSL connection has been closed"):
        conn.cursor().execute("INSERT INTO document_mentions (id) VALUES (%s)", (1,))

    assert server.killed == 1
