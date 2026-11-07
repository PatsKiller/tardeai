"""LQ-20261107-176 — /v3/portfolio/re-entry: "Sell history could not be read."

ANCHOR: REENTRY_EXITS_GAP_20261107. The audit saw the reentry desk's exits panel read
``Sell history could not be read.`` while a standalone ``GET /api/v2/redeploy/history?days=365`` answered with 154
sells. The desk calls the same reader in-process, on the request thread's own DB connection: one transient
statement failure there aborts the thread-local transaction, every later read on it fails too, and the reader's
swallowed exception made the reason invisible. These tests pin the three behaviours that fix it — roll back and
retry once, name the exception when it still fails, and never cache a degraded board.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.errors
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
from lib import desks_a  # noqa: E402
from lib import redeploy_capital_book  # noqa: E402

NOW = datetime(2026, 11, 7, 17, tzinfo=timezone.utc)
ABORTED = psycopg2.errors.InFailedSqlTransaction(
    "current transaction is aborted, commands ignored until end of transaction block")


class _FakeConn:
    def __init__(self):
        self.calls: list[str] = []

    def cursor(self):
        self.calls.append("cursor")
        return object()

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")


def _patch_conn(monkeypatch):
    import db_adapter

    conn = _FakeConn()
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    return conn


def _workbench_gap(payload) -> str:
    tab = payload["tabs"]["exits-review"]
    return next(p for p in tab["panels"] if p.get("id") == "workbench")["gap"]


# ── the reader: roll back, retry once, then name what failed ──────────────────


def test_a_transient_failure_is_rolled_back_and_retried_once(monkeypatch):
    conn = _patch_conn(monkeypatch)
    answers = [ABORTED, {"ok": True, "rows": [{"symbol": "AAA"}]}]

    def fake_build(cur, *, days=3650):
        out = answers.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(redeploy_capital_book, "build_history", fake_build)
    assert api_v2._redeploy_history({"days": "365"}) == {"ok": True, "rows": [{"symbol": "AAA"}]}
    assert conn.calls == ["cursor", "rollback", "cursor", "commit"], \
        "the aborted transaction is cleared before the retry, and the retry's read is committed"


def test_after_the_retry_it_names_the_exception_instead_of_a_bare_ok_false(monkeypatch, capsys):
    _patch_conn(monkeypatch)

    def always_aborted(cur, *, days=3650):
        raise ABORTED

    monkeypatch.setattr(redeploy_capital_book, "build_history", always_aborted)
    res = api_v2._redeploy_history({"days": "365"})
    assert res["ok"] is False
    assert res["error_type"] == "InFailedSqlTransaction", "the page and the log need the exception's name"
    assert "current transaction is aborted" in res["error"]
    assert "InFailedSqlTransaction" in capsys.readouterr().err, "the server log gets the failure too"


def test_a_rollback_that_itself_fails_is_reported_beside_the_read_error(monkeypatch, capsys):
    """The rollback guard must never be a silent ``except: pass`` — a broken connection is news."""
    import db_adapter

    class _DeadConn(_FakeConn):
        def rollback(self):
            super().rollback()
            raise RuntimeError("connection already closed")

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: _DeadConn())

    def always_aborted(cur, *, days=3650):
        raise ABORTED

    monkeypatch.setattr(redeploy_capital_book, "build_history", always_aborted)
    res = api_v2._redeploy_history({"days": "365"})
    assert res["error_type"] == "InFailedSqlTransaction"
    assert res["rollback_error"] == "RuntimeError: connection already closed"
    logged = capsys.readouterr().err
    assert "InFailedSqlTransaction" in logged and "and the rollback failed: RuntimeError" in logged


# ── the desk: the gap carries the reason it used to swallow ──────────────────


def test_the_desk_gap_carries_the_reason_it_used_to_swallow():
    exits = {"ok": False, "error": "current transaction is aborted", "error_type": "InFailedSqlTransaction"}
    out = desks_a.reentry_payload(root=ROOT, now=NOW, packets={}, exits=exits, states={})
    gap = _workbench_gap(out)
    assert gap.startswith("Sell history could not be read.")
    assert "InFailedSqlTransaction" in gap and "current transaction is aborted" in gap


def test_an_unreadable_desk_with_no_reason_keeps_the_old_sentence():
    out = desks_a.reentry_payload(root=ROOT, now=NOW, packets={}, exits=None, states={})
    assert _workbench_gap(out) == "Sell history could not be read."


def test_a_healthy_read_still_shows_no_gap():
    out = desks_a.reentry_payload(root=ROOT, now=NOW, packets={}, exits={"ok": True, "rows": []}, states={})
    assert _workbench_gap(out) is None


# ── the route: a degraded board is never cached ─────────────────────────────


def _patch_payload_readers(monkeypatch):
    class _Truth:
        def resolve(self, root, db_query=None):
            return {}

        def stances_for_symbols(self, symbols, root=None, db_query=None):
            return {}

    monkeypatch.setattr(api_v2, "_cio_truth_readers", lambda: _Truth())
    monkeypatch.setattr(api_v2, "_buy_ready_packets_index", lambda: {"rows": []})
    monkeypatch.setattr(desks_a, "build", lambda desk, **kw: {"ok": True, "data": {}})
    monkeypatch.setattr(api_v2, "_DESKS_A_CACHE", {})


def test_a_degraded_reentry_board_is_not_cached(monkeypatch):
    _patch_payload_readers(monkeypatch)

    monkeypatch.setattr(api_v2, "_redeploy_history",
                        lambda q=None: {"ok": False, "error": "boom", "error_type": "InterfaceError"})
    api_v2._desks_a_payload("reentry")
    assert "reentry" not in api_v2._DESKS_A_CACHE, \
        "one transient failure must not be served for the whole 60 s window"

    monkeypatch.setattr(api_v2, "_redeploy_history", lambda q=None: {"ok": True, "rows": []})
    api_v2._desks_a_payload("reentry")
    assert "reentry" in api_v2._DESKS_A_CACHE, "a complete board is cached as before"


def test_a_complete_reentry_board_is_still_served_from_cache(monkeypatch):
    _patch_payload_readers(monkeypatch)
    monkeypatch.setattr(api_v2, "_redeploy_history", lambda q=None: {"ok": True, "rows": []})
    first = api_v2._desks_a_payload("reentry")
    monkeypatch.setattr(api_v2, "_redeploy_history", lambda q=None: pytest.fail("cache miss inside the window"))
    assert api_v2._desks_a_payload("reentry") is first
