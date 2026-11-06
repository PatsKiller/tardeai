"""daily-incubator-refresh: a closed connection no longer masks the real error (2026-10-16).

Live run 08:15 ET 2026-10-16 (n8n canary): the server's idle guard closed the connection, and the except handler's
``conn.rollback()`` raised ``psycopg2.InterfaceError: connection already closed`` — the log showed that, not the
original failure. Pins:
1. the except handler logs the ORIGINAL exception and skips rollback on a closed connection (no second raise);
2. a connection closed before the scan-refresh commit is reopened via ``_ensure_conn`` (and the loss is counted),
   instead of crashing on commit().

Hermetic: fake connections only; no DB, no .env, no network.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import daily_incubator_refresh as R  # noqa: E402


class InterfaceError(Exception):
    pass


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [("id",), ("symbol",)]

    def execute(self, sql, params=None):
        if self.conn.closed:
            raise InterfaceError("connection already closed")
        if self.conn.dead:
            # The server closed the socket; psycopg's closed flag stays 0.
            raise RuntimeError("SSL connection has been closed unexpectedly")
        self.conn.sql.append(sql)
        if self.conn.raise_on_execute and "incubator_universe" in sql and "SELECT symbol" in sql:
            raise RuntimeError("original failure: catalyst query exploded")

    def fetchall(self):
        return list(self.conn.rows)


class FakeConn:
    def __init__(self, rows=(), *, raise_on_execute=False):
        self.closed = 0
        self.dead = 0                 # server-side socket drop; ``closed`` stays 0
        self.die_after_commits = None
        self.rows = list(rows)
        self.sql: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.raise_on_execute = raise_on_execute

    def cursor(self):
        if self.closed:
            raise InterfaceError("connection already closed")
        return FakeCursor(self)

    def commit(self):
        if self.closed:
            raise InterfaceError("connection already closed")
        if self.dead:
            raise RuntimeError("SSL connection has been closed unexpectedly")
        self.commits += 1
        if self.die_after_commits is not None and self.commits >= self.die_after_commits:
            self.dead = 1

    def rollback(self):
        if self.closed:
            raise InterfaceError("connection already closed")
        self.rollbacks += 1

    def close(self):
        if self.closed:
            raise InterfaceError("connection already closed")
        self.closed = 1


def test_safe_rollback_skips_closed_connection():
    c = FakeConn()
    c.closed = 1
    R._safe_rollback(c)        # must not raise
    R._safe_close(c)           # must not raise
    assert c.rollbacks == 0


def test_original_exception_logged_not_masked(monkeypatch, caplog):
    conn = FakeConn(rows=[], raise_on_execute=True)

    def boom_after_close(sql, params=None):
        raise RuntimeError("original failure: active query exploded")

    monkeypatch.setattr(R, "get_conn", lambda: conn)
    real_cursor = conn.cursor

    def cursor():
        cur = real_cursor()
        cur.execute = boom_after_close
        conn.closed = 1            # the idle guard closes the connection while the error unwinds
        return cur

    conn.cursor = cursor
    caplog.set_level(logging.INFO, logger="daily_incubator_refresh")
    with pytest.raises(SystemExit) as exc:
        R._run(argparse.Namespace(dry_run=False, apply=True))
    assert exc.value.code == 1
    text = caplog.text
    assert "original failure: active query exploded" in text
    assert "rollback skipped: connection already closed" in text
    assert "InterfaceError" not in text.split("daily_incubator_refresh failed", 1)[0]


def test_closed_before_scan_refresh_commit_reconnects(monkeypatch, caplog):
    first = FakeConn(rows=[(1, "AAA")])
    second = FakeConn(rows=[])
    conns = iter([first, second])
    monkeypatch.setattr(R, "get_conn", lambda: next(conns))

    def refresh(conn, inc, dry_run=False):
        conn.closed = 1            # the server idle guard fires during the scan-refresh loop
        return "stayed_active"

    monkeypatch.setattr(R, "refresh_ticker", refresh)
    monkeypatch.setitem(sys.modules, "catalyst_enrichment", type(sys)("catalyst_enrichment"))
    sys.modules["catalyst_enrichment"].enrich_ticker = lambda sym: {}
    caplog.set_level(logging.INFO, logger="daily_incubator_refresh")
    out = R._run(argparse.Namespace(dry_run=False, apply=True))
    assert out["scan_refresh_lost"] == 1
    assert second.commits == 2          # scan-refresh commit + catalyst commit, both on the reopened connection
    assert first.commits == 0
    assert "uncommitted rows were lost" in caplog.text
    assert second.closed == 1


# ── 2026-11-03: the server closes the socket while psycopg's closed flag stays 0 ──────────

def test_dead_socket_with_closed_zero_is_not_trusted(monkeypatch):
    first = FakeConn()
    first.dead = 1                  # server dropped the socket; ``closed`` stays 0
    second = FakeConn()
    monkeypatch.setattr(R, "get_conn", lambda: second)
    assert R._ensure_conn(first) is second


def test_catalyst_updates_are_committed_per_symbol(monkeypatch):
    conn = FakeConn(rows=[(10, "LNSR"), (11, "SGHT")])
    monkeypatch.setattr(R, "get_conn", lambda: conn)
    monkeypatch.setattr(R, "refresh_ticker", lambda c, inc, dry_run=False: "stayed_active")
    monkeypatch.setitem(sys.modules, "catalyst_enrichment", type(sys)("catalyst_enrichment"))
    sys.modules["catalyst_enrichment"].enrich_ticker = lambda sym: {
        "has_fresh_catalyst": True, "catalyst_summary": "fresh"}
    out = R._run(argparse.Namespace(dry_run=False, apply=True))
    assert out["catalyst_refreshed"] == 2
    # scan-refresh commit + one commit per catalyst symbol + the final no-op commit
    assert conn.commits == 4
    assert len([s for s in conn.sql if "UPDATE incubator_universe" in s]) == 2


def test_catalyst_batch_survives_a_socket_drop_between_symbols(monkeypatch, caplog):
    first = FakeConn(rows=[(10, "LNSR"), (11, "SGHT")])
    first.die_after_commits = 2      # scan commit + symbol 1 commit land, then the socket dies
    second = FakeConn(rows=[])
    conns = iter([first, second])
    monkeypatch.setattr(R, "get_conn", lambda: next(conns))
    monkeypatch.setattr(R, "refresh_ticker", lambda c, inc, dry_run=False: "stayed_active")
    monkeypatch.setitem(sys.modules, "catalyst_enrichment", type(sys)("catalyst_enrichment"))
    sys.modules["catalyst_enrichment"].enrich_ticker = lambda sym: {
        "has_fresh_catalyst": True, "catalyst_summary": "fresh"}
    caplog.set_level(logging.INFO, logger="daily_incubator_refresh")
    out = R._run(argparse.Namespace(dry_run=False, apply=True))
    assert out["catalyst_refreshed"] == 2             # symbol 1 committed before the drop; symbol 2 on the new conn
    assert first.commits == 2 and second.commits == 2  # symbol 2 + final commit on the reopened connection
    assert "uncommitted rows were lost" not in caplog.text
