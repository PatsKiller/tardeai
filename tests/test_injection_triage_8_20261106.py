"""Injection triage batch 8: SQL time windows travel as driver parameters, never in SQL text.

ANCHOR: INJECTION_TRIAGE_8_20261106

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

    def __init__(self, fetchall_rows=None):
        self.calls: list[tuple[str, object]] = []
        self._fetchall_rows = fetchall_rows if fetchall_rows is not None else []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return (0,)

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


def _assert_param_not_sql(calls, value):
    assert calls
    for sql, params in calls:
        assert str(value) not in sql
        assert "DROP TABLE" not in sql
        assert params is not None and value in params
        assert sql.count("%s") == len(params)


# --- hermes_cross_source_synthesizer (FIX: hours was spliced into four INTERVAL literals) ------------------

def test_cross_source_bundle_window_is_a_param():
    mod = importlib.import_module("hermes_cross_source_synthesizer")
    cur = RecordingCursor()
    mod.collect_signal_bundle(RecordingConn(cur), hours=HOSTILE)
    windowed = [c for c in cur.calls if c[1] is not None]
    assert len(windowed) == 4
    _assert_param_not_sql(windowed, HOSTILE)
    for sql, _ in windowed:
        assert "%s * INTERVAL '1 hour'" in sql


# --- hermes_news_bridge (FIX: interval '%s hours' quoted the param inside a literal) -----------------------

def test_news_bridge_lookback_is_a_param_outside_any_literal(monkeypatch):
    mod = importlib.import_module("hermes_news_bridge")
    cur = RecordingCursor()
    monkeypatch.setattr(mod, "load_env", lambda: None)
    monkeypatch.setattr(mod, "db", lambda: RecordingConn(cur))
    mod.run(limit=5, lookback_hours=HOSTILE)
    sql, params = cur.calls[0]
    assert HOSTILE not in sql
    assert "'%s" not in sql                       # the placeholder no longer sits inside a quoted literal
    assert "now() - %s * interval '1 hour'" in sql
    assert params == list(mod.BRIDGE_TYPES) + [HOSTILE, 5]
    assert sql.count("%s") == len(params)


# --- hermes_outcome_grader (FIX: the refresh window from config was spliced into SQL text) -----------------

def test_outcome_grader_refresh_window_is_a_param():
    mod = importlib.import_module("hermes_outcome_grader")
    cur = RecordingCursor()
    mod.refresh_close_cache(cur, {"close_cache_refresh_days": "4"})
    sql, params = cur.calls[0]
    assert "make_interval(days => %s)" in sql and params == (4,)
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.refresh_close_cache(cur, {"close_cache_refresh_days": HOSTILE})
    assert cur.calls == []
    cur = RecordingCursor()
    mod.refresh_close_cache(cur, {}, backfill=True)
    sql, params = cur.calls[0]
    assert params is None and "%s" not in sql and "WHERE price IS NOT NULL" in sql


# --- hermes_scalp_shadow_feeder (FIX: int(days) was spliced into SQL text) --------------------------------

def test_scalp_feeder_days_is_a_param(monkeypatch):
    mod = importlib.import_module("hermes_scalp_shadow_feeder")
    cur = RecordingCursor()
    fake_db = types.ModuleType("db_adapter")
    fake_db._get_conn = lambda: RecordingConn(cur)
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    fake_persist = types.ModuleType("persist_shadow_scores")
    fake_persist.DDL = "SELECT 1"
    fake_persist.persist = lambda *a, **k: pytest.fail("persist called on a dry run")
    monkeypatch.setitem(sys.modules, "persist_shadow_scores", fake_persist)
    out = mod.run(apply=False, days=12)
    assert out["candidates"] == 0
    sql, params = cur.calls[1]
    assert params == (12,) and "12" not in sql
    assert "%s * INTERVAL '1 day'" in sql
    assert "ILIKE '%%scalp%%'" in sql             # doubled so the driver emits a single % wildcard
    with pytest.raises(ValueError):
        mod.run(apply=False, days=HOSTILE)


# --- generate_phase5_learning_recommendations (FIX: %-formatted window and threshold) ----------------------

def test_phase5_window_and_threshold_are_params(monkeypatch, capsys):
    mod = importlib.import_module("generate_phase5_learning_recommendations")
    cur = RecordingCursor()
    monkeypatch.setattr(mod, "get_conn", lambda: RecordingConn(cur))
    monkeypatch.setattr(sys, "argv", ["generate_phase5_learning_recommendations.py",
                                      "--since-days", "17", "--min-observations", "23"])
    mod.main()
    (sql1, p1), (sql2, p2) = cur.calls
    assert p1 == (17,) and p2 == (17, 23)
    for sql, params in cur.calls:
        assert "17" not in sql and "23" not in sql
        assert sql.count("%s") == len(params)
