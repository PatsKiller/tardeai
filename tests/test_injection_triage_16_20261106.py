"""Injection triage batch 16: SQL values travel as driver parameters, identifiers only from allowlists.

ANCHOR: INJECTION_TRIAGE_16_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair, and the real functions are driven
through it. A hostile value must arrive in params (or be refused before any SQL runs), never in SQL text.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    """Records (sql, params); answers fetchone/fetchall with harmless fixed shapes."""

    def __init__(self, fetchone_row=(0, None), fetchall_rows=None):
        self.calls: list[tuple[str, object]] = []
        self._fetchone_row = fetchone_row
        self._fetchall_rows = fetchall_rows if fetchall_rows is not None else []
        self.rowcount = 0
        self.description = [("c0",)]

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return self._fetchone_row

    def fetchall(self):
        return list(self._fetchall_rows)

    def close(self):
        pass


class RecordingConn:
    def __init__(self, cur):
        self._cur = cur
        self.autocommit = True

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


# --- report_proposal_supply_funnel (FIX: the day window was spliced into INTERVAL '<n> days') -------------

def test_supply_funnel_window_is_a_param(monkeypatch):
    mod = importlib.import_module("report_proposal_supply_funnel")
    cur = RecordingCursor(fetchone_row=(0,))
    monkeypatch.setattr(mod, "get_conn", lambda: RecordingConn(cur))
    mod.build_report(since_days=7)
    windowed = [(sql, params) for sql, params in cur.calls if "INTERVAL" in sql]
    assert len(windowed) == 12
    for sql, params in windowed:
        assert "'7 days'" not in sql and "{interval}" not in sql
        assert "%s * INTERVAL '1 day'" in sql
        assert list(params) == [7]
        assert sql.count("%s") == len(params)


# --- report_phase6_stale_proposals (FIX: terminal list + day window were spliced into SQL text) -----------

def test_phase6_stale_report_values_are_params(monkeypatch):
    mod = importlib.import_module("report_phase6_stale_proposals")
    cur = RecordingCursor(fetchone_row=(0, None))
    monkeypatch.setattr(mod, "get_conn", lambda: RecordingConn(cur))
    monkeypatch.setattr(sys, "argv", ["report_phase6_stale_proposals.py", "--since-days", "9", "--limit", "5"])
    mod.main()
    (list_sql, list_params), (sweep_sql, sweep_params) = cur.calls
    policy = importlib.import_module("phase6_proposal_staleness_policy")
    assert "<> ALL(%s)" in list_sql and "NOT IN" not in list_sql
    assert "'REJECTED'" not in list_sql
    assert list_params == [sorted(policy.TERMINAL_STATUSES), 5]
    assert "'9 days'" not in sweep_sql and sweep_params == [9]


# --- reset_stuck_agent_jobs / run_sec_form4_momentum_context (FIX: '%s minutes' / '%s days' via % format) ---

def test_reset_stuck_agent_jobs_minutes_are_params():
    mod = importlib.import_module("reset_stuck_agent_jobs")
    cur = RecordingCursor()
    conn = RecordingConn(cur)
    mod.find_stuck(conn, 45)
    mod.reset(conn, 45)
    mod.find_stuck_synthesis(conn, 45)
    mod.reset_synthesis(conn, 45)
    assert len(cur.calls) == 4
    for sql, params in cur.calls:
        assert "45" not in sql and "minutes'" not in sql
        assert "%s * interval '1 minute'" in sql
        assert params == (45,)


def test_form4_momentum_symbols_window_and_limit_are_params():
    mod = importlib.import_module("run_sec_form4_momentum_context")
    cur = RecordingCursor()
    mod._momentum_symbols(RecordingConn(cur), days=3)
    (sql, params), = cur.calls
    assert "'3 days'" not in sql and "LIMIT %s" in sql
    assert params == (3, mod.MAX_SYMBOLS)


# --- identifier allowlists / fixed tables (SAFE after the check) -----------------------------------------

def test_trade_lesson_counts_refuse_unlisted_column():
    mod = importlib.import_module("report_trade_lesson_memory")
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod._query_counts(cur, HOSTILE, "2026-01-01")
    assert cur.calls == []
    mod._query_counts(cur, "strategy_id", "2026-01-01")
    assert cur.calls[0][1] == ("2026-01-01",)


def test_reports_portal_purge_preview_age_is_a_param(monkeypatch):
    mod = importlib.import_module("reports_portal")
    cur = RecordingCursor(fetchone_row=(0,))
    monkeypatch.setattr(mod, "_conn", lambda: RecordingConn(cur))
    out = mod.purge(None, older_than_days=45, apply=False)
    assert out["ok"] is True
    assert len(cur.calls) == 4
    for sql, params in cur.calls:
        assert "45 days" not in sql
        assert "%s * INTERVAL '1 day'" in sql
        assert params[-1] == 45
        assert sql.count("%s") == len(params)
