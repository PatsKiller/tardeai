"""Injection triage batch 15: SQL values travel as driver parameters, identifiers only after a check.

ANCHOR: INJECTION_TRIAGE_15_20261106

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
        self.description = [("c0",), ("c1",)]

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return (0, 0)

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


# --- replay_social_route_policy (FIX: the day window was spliced into an INTERVAL literal) ---------------

def test_replay_social_route_policy_window_is_a_param(monkeypatch):
    mod = importlib.import_module("replay_social_route_policy")
    cur = RecordingCursor()
    fake_db = types.ModuleType("db_adapter")
    fake_db.get_connection = lambda: RecordingConn(cur)
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    fake_route = types.ModuleType("social_route_policy")
    fake_route.route_social_candidate = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "social_route_policy", fake_route)
    fake_runner = types.ModuleType("continuous_runner")
    fake_runner.classify_social_injection = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "continuous_runner", fake_runner)

    out = mod.build(45)
    assert out["ok"] is True and out["rows_replayed"] == 0
    assert len(cur.calls) == 1
    sql, params = cur.calls[0]
    assert "45" not in sql
    assert "%s * INTERVAL '1 day'" in sql
    assert params == (45,)


# --- report_phase6_approval_audit (FIX: --since-days was spliced into an INTERVAL literal) ---------------

def test_phase6_audit_window_and_filters_are_params(monkeypatch, tmp_path):
    mod = importlib.import_module("report_phase6_approval_audit")
    cur = RecordingCursor()
    monkeypatch.setattr(mod, "get_conn", lambda: RecordingConn(cur))
    out_json = tmp_path / "audit.json"
    monkeypatch.setattr(sys, "argv", [
        "report_phase6_approval_audit.py", "--since-days", "7", "--symbol", HOSTILE,
        "--limit", "5", "--output-json", str(out_json),
    ])
    mod.main()
    assert out_json.exists()
    assert len(cur.calls) == 4
    for sql, params in cur.calls:
        assert HOSTILE not in sql and "DROP TABLE" not in sql
        assert "'7 days'" not in sql
        assert sql.count("%s") == len(params)
        assert params[0] == 7 and params[1] == HOSTILE
    assert cur.calls[2][1][-1] == 5          # LIMIT stays a param


# --- prune_document_mentions (SAFE after check: identifiers regex-checked in the same function) ----------

def test_prune_refuses_a_hostile_identifier_before_sql(monkeypatch):
    mod = importlib.import_module("prune_document_mentions")
    import lib.document_mentions as dm

    monkeypatch.setattr(dm, "SOURCES", {HOSTILE: {"id": "id"}})
    monkeypatch.setattr(mod, "retention_windows", lambda: {})
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.plan(RecordingConn(cur))
    assert cur.calls == []

    monkeypatch.setattr(dm, "SOURCES", {"news_articles": {"id": "id"}})
    monkeypatch.setattr(mod, "retention_windows", lambda: {"news_articles": (HOSTILE, 30)})
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.plan(RecordingConn(cur))
    assert all(HOSTILE not in sql for sql, _ in cur.calls)


def test_prune_every_real_source_and_window_passes_the_check():
    """The check must not refuse a name a real caller passes: every SOURCES table/id and every
    db_retention.POLICIES timestamp column matches the identifier regex."""
    mod = importlib.import_module("prune_document_mentions")
    from lib.document_mentions import SOURCES
    import db_retention

    for table, spec in SOURCES.items():
        assert mod._IDENT.match(table) and mod._IDENT.match(spec["id"])
    for _table, col, _days in db_retention.POLICIES:
        assert mod._IDENT.match(col)
    cur = RecordingCursor()
    mod.prune(RecordingConn(cur), apply=True)
    assert cur.calls
    for sql, params in cur.calls:
        assert params[0] in SOURCES
