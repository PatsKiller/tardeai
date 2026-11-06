"""Injection triage batch 14: SQL values travel as driver parameters, identifiers only from allowlists.

ANCHOR: INJECTION_TRIAGE_14_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair, and the real functions are driven
through it. A hostile value must arrive in params (or be refused before any SQL runs), never in SQL text.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    """Records (sql, params); answers fetchone/fetchall with harmless fixed shapes."""

    def __init__(self, fetchall_rows=None):
        self.calls: list[tuple[str, object]] = []
        self._fetchall_rows = fetchall_rows if fetchall_rows is not None else []
        self.description = [("title",), ("published_at",)]
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return None

    def fetchall(self):
        return list(self._fetchall_rows)

    def close(self):
        pass


class RecordingConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _assert_clean(sql: str):
    assert HOSTILE not in sql
    assert "DROP TABLE" not in sql


# --- process_watchlist_agent_jobs._wait_setup_symbol_set (FIX: hours were spliced into an INTERVAL literal) -------

def test_wait_setup_window_is_a_param(monkeypatch):
    mod = importlib.import_module("process_watchlist_agent_jobs")
    monkeypatch.setattr(mod, "WAIT_SETUP_HOURS", 48)
    monkeypatch.setattr(mod, "WAIT_SETUP_LIMIT", 7)
    cur = RecordingCursor(fetchall_rows=[("aapl",), (None,)])
    assert mod._wait_setup_symbol_set(RecordingConn(cur)) == frozenset({"AAPL"})
    sql, params = cur.calls[-1]
    assert "%s * INTERVAL '1 hour'" in sql
    assert "48" not in sql
    assert params == (48, 7)
    assert sql.count("%s") == len(params)


# --- process_watchlist_agent_jobs._update_maturity (SAFE: column from a fixed allowlist) -------------------------

def test_update_maturity_refuses_a_hostile_agent_name():
    mod = importlib.import_module("process_watchlist_agent_jobs")
    cur = RecordingCursor()
    mod._update_maturity(RecordingConn(cur), "AAPL", HOSTILE, "completed")
    assert cur.calls == []


# --- proposal_catalyst_quality.get_news_for_symbol (FIX: look-back hours were spliced into an INTERVAL literal) ---

def test_catalyst_news_symbol_and_hours_are_params(monkeypatch):
    mod = importlib.import_module("proposal_catalyst_quality")
    monkeypatch.setattr(mod, "_table_exists", lambda conn, table: True)
    monkeypatch.setattr(mod, "_table_has_column", lambda conn, table, column: False)
    cur = RecordingCursor(fetchall_rows=[("t", "2026-11-06")])
    out = mod.get_news_for_symbol(RecordingConn(cur), HOSTILE, hours_back=36)
    assert out == [{"title": "t", "published_at": "2026-11-06"}]
    sql, params = cur.calls[-1]
    _assert_clean(sql)
    assert "SELECT title, published_at FROM news_articles" in sql
    assert "%s * INTERVAL '1 hour'" in sql
    assert params == [HOSTILE, 36]
    assert sql.count("%s") == len(params)


# --- proposal_backtest_engine.main (FIX: LIMIT was spliced into SQL text) -----------------------------------------

def _fake_receipts():
    lr = types.SimpleNamespace()
    lr.enforce_readonly = lambda conn: None
    lr.write_lane_receipt = lambda *a, **k: None
    lr.dry_run_report = lambda *a, **k: None
    return lr


def test_backtest_limit_and_strategy_are_params(monkeypatch, capsys):
    mod = importlib.import_module("proposal_backtest_engine")
    cur = RecordingCursor()
    monkeypatch.setattr(mod, "get_conn", lambda: RecordingConn(cur))
    monkeypatch.setattr(mod, "_receipt_lib", _fake_receipts)
    assert mod.main(["--pending", "--strategy", HOSTILE, "--limit", "5"]) == 0
    sql, params = cur.calls[-1]
    _assert_clean(sql)
    assert sql.rstrip().endswith("LIMIT %s")
    assert params == [["PENDING", "APPROVED_FOR_PAPER_TEST"], HOSTILE, 5]
    assert sql.count("%s") == len(params)


def test_backtest_without_limit_has_no_limit_clause(monkeypatch, capsys):
    mod = importlib.import_module("proposal_backtest_engine")
    cur = RecordingCursor()
    monkeypatch.setattr(mod, "get_conn", lambda: RecordingConn(cur))
    monkeypatch.setattr(mod, "_receipt_lib", _fake_receipts)
    assert mod.main(["--pending"]) == 0
    sql, params = cur.calls[-1]
    assert "LIMIT" not in sql
    assert params == [["PENDING", "APPROVED_FOR_PAPER_TEST"]]
