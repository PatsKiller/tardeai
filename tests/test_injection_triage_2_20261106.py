"""Injection triage batch 2: SQL built from f-strings carries values as driver params.

ANCHOR: INJECTION_TRIAGE_2_20261106

agent_outcome_scorer.rebuild_calibration interpolated its window into INTERVAL text; it is now a
parameter. The other flagged calls in the batch interpolate only module-constant identifiers and are
marked SAFE; these tests drive three of them with a recording cursor to show that a hostile value
reaches the driver as a parameter and never appears in the SQL text.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_outcome_scorer  # noqa: E402
from agent_runtime.trigger_intake import PostgresTriggerIntakeStore  # noqa: E402

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    def __init__(self, rows_by_marker=None):
        self.calls: list[tuple[str, object]] = []
        self._rows_by_marker = rows_by_marker or {}
        self._last = ""
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._last = sql

    def _rows(self):
        for marker, rows in self._rows_by_marker.items():
            if marker in self._last:
                return rows
        return []

    def fetchall(self):
        return list(self._rows())

    def fetchone(self):
        rows = self._rows()
        return rows[0] if rows else None

    def close(self):
        pass


class RecordingConn:
    def __init__(self, cursor):
        self.cur = cursor
        self.commits = 0

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _assert_not_in_sql(calls, value):
    for sql, _ in calls:
        assert value not in sql, sql


def test_rebuild_calibration_window_and_agent_are_params():
    cur = RecordingCursor({
        "SELECT DISTINCT agent_name": [(HOSTILE,)],
        "COUNT(CASE WHEN verdict='CORRECT'": [(4, 3, 1, 0, 0.7, 1.5, 100.0)],
        "AVG(CASE WHEN verdict='CORRECT'": [(0.75,)],
    })
    conn = RecordingConn(cur)
    agent_outcome_scorer.rebuild_calibration(conn)

    _assert_not_in_sql(cur.calls, HOSTILE)
    distinct = [(s, p) for s, p in cur.calls if "SELECT DISTINCT agent_name" in s]
    assert [p for _, p in distinct] == [[30], [90], [365]]
    for sql, _ in distinct:
        assert "%s * INTERVAL '1 day'" in sql
        assert "{" not in sql
    stats = [(s, p) for s, p in cur.calls if "COUNT(CASE WHEN verdict='CORRECT'" in s]
    assert [p for _, p in stats] == [[HOSTILE, 30], [HOSTILE, 90], [HOSTILE, 365]]
    for sql, params in stats:
        assert sql.count("%s") == len(params)
    inserts = [p for s, p in cur.calls if "INSERT INTO agent_calibration" in s]
    assert len(inserts) == 3 and all(p[0] == HOSTILE for p in inserts)
    assert conn.commits == 1


def _store(cur):
    return PostgresTriggerIntakeStore(
        lambda: RecordingConn(cur), clock=lambda: "2026-11-06T00:00:00+00:00", verify_identity=False
    )


def test_trigger_intake_cursor_values_are_params():
    cur = RecordingCursor({"SELECT cursor_value": [("c1",)]})
    store = _store(cur)
    store.set_cursor(HOSTILE, HOSTILE, HOSTILE, agent_id=HOSTILE)
    assert store.get_cursor(HOSTILE, HOSTILE) == "c1"
    _assert_not_in_sql(cur.calls, HOSTILE)
    sqls = [s for s, _ in cur.calls]
    assert any("INSERT INTO agentic_runtime.trigger_source_cursors" in s for s in sqls)
    assert any("FROM agentic_runtime.trigger_source_cursors" in s for s in sqls)
    params = [p for s, p in cur.calls if "trigger_source_cursors" in s]
    assert params[0][:4] == (HOSTILE, HOSTILE, HOSTILE, HOSTILE)
    assert params[1] == (HOSTILE, HOSTILE)


def test_trigger_intake_queue_stats_agent_is_param():
    cur = RecordingCursor({"count(*) FILTER": [(1, 0, 0, 0, 0, None)]})
    stats = _store(cur).queue_stats(HOSTILE)
    assert stats["queued"] == 1
    _assert_not_in_sql(cur.calls, HOSTILE)
    sql, params = [(s, p) for s, p in cur.calls if "count(*) FILTER" in s][0]
    assert "FROM agentic_runtime.trigger_intake" in sql and params == (HOSTILE,)


def test_account_policy_key_is_param(monkeypatch):
    import account_policy

    cur = RecordingCursor({"FROM account_automation_policies": []})
    monkeypatch.setattr(account_policy, "_get_conn", lambda: RecordingConn(cur))
    out = account_policy.load_policy(HOSTILE)
    assert out["sizing_engine"] == "fixed_dollar"
    _assert_not_in_sql(cur.calls, HOSTILE)
    sql, params = cur.calls[0]
    assert params == (HOSTILE,)
    assert "p.automation_mode" in sql and "p.daily_loss_pause_pct" in sql
