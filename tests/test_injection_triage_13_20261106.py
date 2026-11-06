"""Injection triage batch 13: SQL values travel as driver parameters, identifiers only from constants.

ANCHOR: INJECTION_TRIAGE_13_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair, and the real functions are driven
through it. A value that used to be spliced into SQL text (an INTERVAL day count, a LIMIT, a symbol) must
arrive in params, never in SQL text.
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
    """Records (sql, params); answers fetches with harmless fixed shapes."""

    def __init__(self, fetchall_rows=None, stop_after=None):
        self.calls: list[tuple[str, object]] = []
        self._fetchall_rows = fetchall_rows if fetchall_rows is not None else []
        self._stop_after = stop_after
        self.description = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        if self._stop_after is not None and len(self.calls) >= self._stop_after:
            raise _Stop()

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return list(self._fetchall_rows)

    def close(self):
        pass


class _Stop(Exception):
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


def _fake_db(monkeypatch, cur):
    fake = types.ModuleType("db_adapter")
    fake.get_connection = lambda: RecordingConn(cur)
    fake._get_conn = fake.get_connection
    monkeypatch.setitem(sys.modules, "db_adapter", fake)


# --- momentum_scalp_freshness_sla_report (FIX: the day window was spliced into an INTERVAL literal) ---------

def test_freshness_report_window_is_a_param(monkeypatch):
    mod = importlib.import_module("momentum_scalp_freshness_sla_report")
    cur = RecordingCursor()
    _fake_db(monkeypatch, cur)
    mod.build(days=17)
    window_calls = [(s, p) for s, p in cur.calls if "paper_trade_proposals" in s]
    assert len(window_calls) >= 2
    for sql, params in window_calls[:2]:
        assert "17" not in sql
        assert "%s * INTERVAL '1 day'" in sql
        assert params == (17,)
        assert sql.count("%s") == len(params)


def test_freshness_report_refuses_non_integer_window(monkeypatch):
    mod = importlib.import_module("momentum_scalp_freshness_sla_report")
    cur = RecordingCursor()
    _fake_db(monkeypatch, cur)
    with pytest.raises(ValueError):
        mod.build(days=HOSTILE)
    assert cur.calls == []


# --- momentum_scalp_source_latency_sla (FIX: "INTERVAL '%s days'" % int(days)) ------------------------------

def test_source_latency_window_is_a_param():
    mod = importlib.import_module("momentum_scalp_source_latency_sla")
    cur = RecordingCursor()
    mod._gather(RecordingConn(cur), 23)
    sql, params = cur.calls[0]
    assert "23" not in sql
    assert "NOW() - %s * INTERVAL '1 day'" in sql
    assert params == (23,)


# --- momentum_scalp_early_lane_runner.scan_counts (FIX: read-only count; window was %-formatted) -----------

def test_early_lane_scan_counts_window_is_a_param(monkeypatch):
    mod = importlib.import_module("momentum_scalp_early_lane_runner")
    cur = RecordingCursor(fetchall_rows=[("GO", None), ("WAIT", "SOCIAL_SCOUT")])
    _fake_db(monkeypatch, cur)
    out = mod.scan_counts(window_days=4)
    assert out == {"rows": 2, "go": 1, "wait": 1, "scout": 1, "ok": True}
    sql, params = cur.calls[0]
    assert "CURRENT_DATE - %s * INTERVAL '1 day'" in sql
    assert params == (4,)


# --- news_to_catalyst.run (FIX: LIMIT is a param; the symbol already was) ---------------------------------

@pytest.mark.parametrize("single_symbol, limit", [(HOSTILE, 50), (None, 500)])
def test_news_to_catalyst_symbol_and_limit_are_params(monkeypatch, single_symbol, limit):
    mod = importlib.import_module("news_to_catalyst")
    cur = RecordingCursor(stop_after=2)  # weights query, then the news query; stop before any write
    monkeypatch.setattr(mod, "_get_conn", lambda: RecordingConn(cur))
    with pytest.raises(_Stop):
        mod.run(single_symbol=single_symbol)
    sql, params = cur.calls[1]
    assert "news_articles" in sql
    assert HOSTILE not in sql and "DROP TABLE" not in sql
    assert "LIMIT %s" in sql
    assert sql.count("%s") == len(params)
    assert params[-1] == limit
    if single_symbol:
        assert params[0] == HOSTILE.upper().strip()
