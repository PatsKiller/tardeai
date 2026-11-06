"""Injection triage batch 6: SQL values travel as driver parameters, identifiers only after a plain-name check.

ANCHOR: INJECTION_TRIAGE_6_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair, and the real functions are driven
through it. A hostile value must arrive in params (or be refused before any SQL runs), never in SQL text.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    """Records (sql, params); answers fetchone/fetchall with harmless fixed shapes."""

    def __init__(self, fetchone=(0,), fetchall_rows=None):
        self.calls: list[tuple[str, object]] = []
        self._one = fetchone
        self._all = fetchall_rows if fetchall_rows is not None else []
        self.description = [("event_id",)]
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def rollback(self):
        pass

    def close(self):
        pass


def _no_hostile_sql(calls):
    for sql, _ in calls:
        assert HOSTILE not in sql and "DROP TABLE" not in sql, sql


# --- communications_portal (SAFE: hub_where builds literal clauses; every filter value is a param) ---------

def test_hub_events_filter_values_arrive_as_params(monkeypatch):
    cp = importlib.import_module("communications_portal")
    cur = RecordingCursor()
    monkeypatch.setattr(cp, "_events_db_conn", lambda: RecordingConn(cur))
    out = cp.hub_events({"q": HOSTILE, "symbol": HOSTILE, "category": HOSTILE, "subject_key": HOSTILE})
    assert out is not None and out["ok"] is True
    assert len(cur.calls) >= 5          # list, total, two facets, lifecycle, reentry
    _no_hostile_sql(cur.calls)
    flat = [p for _, params in cur.calls for p in (params or [])]
    assert any(HOSTILE in str(p) for p in flat)


# --- compare_phase2b / phase2f (FIX: --*-table was spliced unchecked) -------------------------------------

@pytest.mark.parametrize("modname", ["compare_phase2b_parallel_retrieval", "compare_phase2f_global_shadow_retrieval"])
def test_retrieval_compare_refuses_a_hostile_table_before_sql(modname):
    mod = importlib.import_module(modname)
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.search_table(RecordingConn(cur), HOSTILE, [1.0], top_k=3, fetch_limit=7)
    assert cur.calls == []


def test_retrieval_compare_keeps_a_plain_table_and_its_limit_param():
    mod = importlib.import_module("compare_phase2b_parallel_retrieval")
    cur = RecordingCursor()
    cur.description = [("source_type",), ("source_id",), ("title",), ("embedding",)]
    assert mod.search_table(RecordingConn(cur), "content_embeddings_qwen3_test", [1.0], fetch_limit=7) == []
    sql, params = cur.calls[0]
    assert "FROM content_embeddings_qwen3_test" in sql and params == (7,)


def test_shadow_index_refuses_a_hostile_table_before_connecting(monkeypatch):
    mod = importlib.import_module("create_phase2e_qwen3_shadow_index")
    monkeypatch.setattr(mod, "get_conn", lambda: pytest.fail("connected with a hostile --table"))
    monkeypatch.setattr(sys, "argv", ["create_phase2e_qwen3_shadow_index.py", "--apply", "--table", HOSTILE])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


# --- data_plausibility_monitor (FIX: contract identifiers and bounds were spliced unchecked) ---------------

def test_plausibility_contract_with_hostile_identifier_or_bound_fails_before_sql():
    dpm = importlib.import_module("data_plausibility_monitor")
    cur = RecordingCursor(fetchone=(1,))
    bad = [
        {"table": HOSTILE, "column": "c", "rule": "min", "min": 0.0, "severity": "BLOCK"},
        {"table": "t", "column": HOSTILE, "rule": "min", "min": 0.0, "severity": "BLOCK"},
        {"table": "t", "column": "c", "rule": "min", "min": "0 OR 1=1); DROP TABLE t;--", "severity": "BLOCK"},
    ]
    results = dpm.measure(cur, {"contracts": bad, "window_policy": {"default_window_days": 0}})
    assert [r["status"] for r in results] == ["CHECK_FAILED"] * 3
    for sql, _ in cur.calls:
        assert "DROP TABLE" not in sql and "1=1" not in sql, sql


def test_plausibility_valid_contract_renders_unchanged():
    dpm = importlib.import_module("data_plausibility_monitor")
    sql = dpm._violation_predicate({"column": "recom_score", "rule": "range", "min": 1.0, "max": 5.0})
    assert sql == '"recom_score" IS NOT NULL AND NOT ("recom_score" BETWEEN 1.0 AND 5.0)'
    with pytest.raises(ValueError):
        dpm.window_sql(HOSTILE, 30)


# --- db_retention (FIX: registry names reached SQL unchecked; catalog attnames now quoted) -----------------

def test_retention_projection_refuses_a_hostile_registry_name_before_sql():
    dr = importlib.import_module("db_retention")
    for table, col in ((HOSTILE, "created_at"), ("market_quotes", HOSTILE)):
        cur = RecordingCursor()
        with pytest.raises(ValueError):
            dr.project_row(cur, table, col, 30, False)
        assert cur.calls == []


def test_retention_projection_sends_windows_as_params():
    dr = importlib.import_module("db_retention")
    cur = RecordingCursor(fetchone=(1,))
    dr.project_row(cur, "market_quotes", "created_at", 30, False, sample_rows=5)
    windowed = [(s, p) for s, p in cur.calls if "make_interval" in s]
    assert windowed and all(p and 30 in p for _, p in windowed)
    assert all("market_quotes" in s for s, _ in cur.calls[2:])


def test_retention_fk_guard_quotes_catalog_names():
    dr = importlib.import_module("db_retention")
    cur = RecordingCursor(fetchall_rows=[("child", 'a"b', "id")])
    guard = dr.fk_guard(cur, "parent")
    assert guard == ' AND NOT EXISTS (SELECT 1 FROM child ch WHERE ch."a""b" = t."id")'
