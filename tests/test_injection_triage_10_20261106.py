"""Injection triage batch 10: SQL values travel as driver parameters, identifiers only after a same-function check.

ANCHOR: INJECTION_TRIAGE_10_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair, and the real functions are driven
through it. A hostile value must arrive in params (or be refused before any SQL runs), never in SQL text.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import data_domain_readiness as R  # noqa: E402
from scripts.lib import deterministic_integrity as DI  # noqa: E402
from scripts.lib import inbound_identity_tagger as T  # noqa: E402
from scripts.lib import llm_consumption as L  # noqa: E402

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    """Records (sql, params); answers fetchone/fetchall with fixed shapes."""

    def __init__(self, fetchone_rows=None, fetchall_rows=None):
        self.calls: list[tuple[str, object]] = []
        self._one = list(fetchone_rows or [])
        self._all = list(fetchall_rows or [])
        self.rowcount = 0
        self.description = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return self._one.pop(0) if self._one else (0,)

    def fetchall(self):
        return self._all.pop(0) if self._all else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


class RecordingConn:
    def __init__(self, cur):
        self._cur = cur
        self.autocommit = False

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _no_hostile_sql(cur):
    for sql, _ in cur.calls:
        assert HOSTILE not in sql
        assert "DROP TABLE" not in sql


# --- llm_consumption.overview (FIX: the month window was spliced into an INTERVAL literal) ------------------

def _drive_overview(monkeypatch, days):
    cur = RecordingCursor()
    monkeypatch.setattr(L, "ensure_schema", lambda: None)
    monkeypatch.setattr(L, "_conn", lambda: RecordingConn(cur))
    mon = types.ModuleType("scripts.lib.anthropic_monitoring")
    mon.snapshot = lambda root: {}
    mon.unavailable_snapshot = lambda: {}
    rout = types.ModuleType("scripts.lib.anthropic_routing")
    rout.state_root = lambda: None
    monkeypatch.setitem(sys.modules, "scripts.lib.anthropic_monitoring", mon)
    monkeypatch.setitem(sys.modules, "scripts.lib.anthropic_routing", rout)
    out = L.overview(days=days)
    return cur, out


def test_overview_month_window_is_a_param(monkeypatch):
    cur, out = _drive_overview(monkeypatch, 45)
    month = [(s, p) for s, p in cur.calls if "%s * INTERVAL '1 day'" in s]
    assert len(month) == 1
    assert month[0][1] == (45,)
    assert "45" not in month[0][0]
    # the literal windows send no params, so psycopg2 does no %-formatting on them
    literal = [(s, p) for s, p in cur.calls if "GROUP BY model_lane" in s and p is None]
    assert len(literal) == 2
    assert set(out["by_lane"]) == set()


def test_overview_refuses_a_non_integer_window_before_sql(monkeypatch):
    with pytest.raises(ValueError):
        _drive_overview(monkeypatch, HOSTILE)


# --- deterministic_integrity (identifier check in the same function before interpolation) --------------------

def test_empty_join_input_refuses_hostile_table_name():
    cur = RecordingCursor()
    out = DI.check_empty_join_inputs(RecordingConn(cur), [("consumer", HOSTILE)])
    assert cur.calls == []
    assert [f["check"] for f in out] == ["join_input_unreadable"]
    _no_hostile_sql(cur)


def test_empty_join_input_still_counts_a_plain_table():
    cur = RecordingCursor(fetchone_rows=[(5,)])
    assert DI.check_empty_join_inputs(RecordingConn(cur), [("c", "strategy_rule_evaluations")]) == []
    assert cur.calls == [("SELECT count(*) FROM strategy_rule_evaluations", None)]


def test_stale_stores_skip_a_hostile_relname():
    cur = RecordingCursor(fetchall_rows=[[(HOSTILE,)]])
    DI.check_stale_stores(RecordingConn(cur))
    assert len(cur.calls) == 1  # only the catalogue query
    _no_hostile_sql(cur)


# --- data_domain_readiness.pg_table_probe (identifier check in the probe itself) ------------------------------

def test_table_probe_refuses_hostile_identifiers():
    cur = RecordingCursor(fetchone_rows=[(True, 10)], fetchall_rows=[[("created_at",)]])
    probe = R.pg_table_probe(lambda: RecordingConn(cur))
    out = probe(HOSTILE, ["created_at"])
    assert "identifier refused" in (out.get("detail") or "")
    _no_hostile_sql(cur)


def test_table_probe_still_measures_a_plain_table():
    cur = RecordingCursor(fetchone_rows=[(True, 10), (None,)], fetchall_rows=[[("created_at",)]])
    probe = R.pg_table_probe(lambda: RecordingConn(cur))
    out = probe("deploy_events", ["created_at"])
    assert out["state"] == "EMPTY"
    assert cur.calls[-1] == ('SELECT max("created_at") FROM "deploy_events"', None)


# --- inbound_identity_tagger: lineage columns only from TURN_LINEAGE_COLUMNS ----------------------------------

def test_conversation_turn_drops_unlisted_lineage_columns(monkeypatch):
    cur = RecordingCursor()
    monkeypatch.setattr(T, "_turn_lineage", lambda *a, **k: {HOSTILE: "v", "event_id": "e1"})
    T.persist_turn({"resolved": []}, conn=RecordingConn(cur), text="hello", role="operator")
    inserts = [(s, p) for s, p in cur.calls if "INSERT INTO operator_conversation_turns" in s]
    assert inserts, cur.calls
    sql, params = inserts[0]
    assert ", event_id" in sql
    assert sql.count("%s") == len(params)
    _no_hostile_sql(cur)
