#!/usr/bin/env python3
"""scripts/lib/pg_reconnect.py: reconnect-once behaviour on a lost psycopg2 connection.

2026-10-09: a Postgres restart closed topic_ingestion's single long-lived connection mid-run and the
article-save handler crashed the whole run. These tests drive the proxy with fake connections that
raise the real psycopg2 error classes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("pg_reconnect_under_test", ROOT / "scripts" / "lib" / "pg_reconnect.py")
pgr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pgr
_spec.loader.exec_module(pgr)

SSL_LOST = "SSL connection has been closed unexpectedly"


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False
        self._last = None

    def execute(self, sql, params=None):
        if self.closed or self.conn.closed:
            raise psycopg2.InterfaceError("cursor already closed")
        fail = self.conn.fail_on.get(sql)
        if fail:
            self.conn.fail_on.pop(sql)
            self.conn.closed = 2
            raise psycopg2.OperationalError(fail)
        if sql.startswith("BAD"):
            raise psycopg2.OperationalError("canceling statement due to statement timeout")
        self.conn.log.append(sql)
        self._last = sql

    def fetchone(self):
        return (self.conn.name, self._last)

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, name, fail_on=None):
        self.name = name
        self.closed = 0
        self.fail_on = dict(fail_on or {})
        self.log = []
        self.commits = 0

    def cursor(self, *a, **kw):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")
        return FakeCursor(self)

    def commit(self):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")
        self.commits += 1

    def rollback(self):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")

    def close(self):
        self.closed = 1


def make(conns, **kw):
    it = iter(conns)
    made = []

    def factory():
        c = next(it)
        if isinstance(c, Exception):
            raise c
        made.append(c)
        return c

    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("log", lambda m: None)
    return pgr.ReconnectingConnection(factory, **kw), made


def test_lost_first_statement_is_reconnected_and_retried_once():
    c1 = FakeConn("c1", {"SELECT 1": SSL_LOST})
    c2 = FakeConn("c2")
    rc, _ = make([c1, c2])
    cur = rc.cursor()
    cur.execute("SELECT 1")
    assert cur.fetchone() == ("c2", "SELECT 1")
    assert (rc.reconnects, rc.retried_ops, rc.dropped_ops) == (1, 1, 0)
    assert c1.closed and c2.log == ["SELECT 1"]


def test_lost_mid_transaction_reconnects_but_reraises_and_does_not_replay():
    c1 = FakeConn("c1", {"INSERT": SSL_LOST})
    c2 = FakeConn("c2")
    rc, _ = make([c1, c2])
    cur = rc.cursor()
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.OperationalError):
        cur.execute("INSERT")
    assert (rc.reconnects, rc.retried_ops, rc.dropped_ops) == (1, 0, 1)
    assert c2.log == []  # nothing replayed on the new connection
    rc.rollback()  # the caller's handler: fine on the new connection
    cur.execute("SELECT 2")  # the same cursor object rebinds to c2
    assert c2.log == ["SELECT 2"]


def test_old_cursor_rebinds_after_reconnect():
    c1 = FakeConn("c1", {"X": SSL_LOST})
    c2 = FakeConn("c2")
    rc, _ = make([c1, c2])
    held = rc.cursor()  # created before the loss (like main()'s long-lived cursor)
    rc.cursor().execute("X")
    rc.commit()
    held.execute("UPDATE topic_monitor")
    assert c2.log == ["X", "UPDATE topic_monitor"]


def test_rollback_of_a_dead_connection_reconnects_instead_of_raising():
    c1 = FakeConn("c1")
    c2 = FakeConn("c2")
    rc, _ = make([c1, c2])
    c1.closed = 2
    rc.rollback()
    assert rc.reconnects == 1 and rc.raw is c2


def test_commit_of_a_dead_connection_reconnects_and_reraises():
    c1 = FakeConn("c1")
    c2 = FakeConn("c2")
    rc, _ = make([c1, c2])
    c1.closed = 2
    with pytest.raises(psycopg2.InterfaceError):
        rc.commit()
    assert rc.raw is c2 and rc.dropped_ops == 1


def test_non_connection_errors_pass_through_without_reconnect():
    c1 = FakeConn("c1")
    rc, _ = make([c1])
    with pytest.raises(psycopg2.OperationalError):
        rc.cursor().execute("BAD statement")
    assert rc.reconnects == 0 and not rc.exhausted


def test_server_still_down_backs_off_then_reconnects():
    c1 = FakeConn("c1", {"S": "the database system is shutting down"})
    c2 = FakeConn("c2")
    slept = []
    down = psycopg2.OperationalError("the database system is starting up")
    rc, _ = make([c1, down, down, c2], sleep=slept.append, reconnect_delays_s=(1.0, 3.0, 6.0))
    rc.cursor().execute("S")
    assert slept == [1.0, 3.0] and rc.raw is c2 and rc.retried_ops == 1


def test_unreachable_server_raises_exhausted_and_flags_the_run():
    c1 = FakeConn("c1", {"S": SSL_LOST})
    down = psycopg2.OperationalError("could not connect")
    rc, _ = make([c1, down, down], reconnect_delays_s=(1.0,))
    with pytest.raises(pgr.ReconnectExhausted):
        rc.cursor().execute("S")
    assert rc.exhausted


def test_retry_is_once_and_reconnects_are_capped_per_run():
    conns = [FakeConn(f"c{i}", {"S": SSL_LOST}) for i in range(3)]
    rc, _ = make(conns, max_reconnects=2)
    # c0 lost -> reconnect #1 to c1, the single retry is lost too: raised, not retried again
    with pytest.raises(psycopg2.OperationalError):
        rc.cursor().execute("S")
    assert rc.reconnects == 1 and rc.retried_ops == 1
    # next op finds c1 dead when it opens its cursor -> reconnect #2 to c2; S is lost on c2 as well and the
    # third reconnect would exceed the cap
    with pytest.raises(pgr.ReconnectExhausted):
        rc.cursor().execute("S")
    assert rc.exhausted and rc.reconnects == 2


def test_attribute_passthrough_and_context_manager():
    c1 = FakeConn("c1")
    rc, _ = make([c1])
    assert rc.name == "c1"
    with rc.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == ("c1", "SELECT 1")
    rc.close()
    assert c1.closed
