"""Injection triage batch 4: SQL values travel as driver parameters, identifiers only from allowlists.

ANCHOR: INJECTION_TRIAGE_4_20261106

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


# --- backfill_message_identity (FIX: days / excluded types / limit were spliced into SQL text) -------------

def test_message_identity_scope_puts_values_in_params():
    mod = importlib.import_module("backfill_message_identity")
    sql, params = mod._scope_sql(30, (HOSTILE,))
    assert HOSTILE not in sql
    assert "DROP TABLE" not in sql
    assert params == [30, [HOSTILE]]
    assert sql.count("%s") == len(params)


def test_message_identity_main_sends_every_value_as_a_param(monkeypatch, capsys):
    mod = importlib.import_module("backfill_message_identity")
    cur = RecordingCursor()
    fake_db = types.ModuleType("db_adapter")
    fake_db._get_conn = lambda: RecordingConn(cur)
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    fake_ident = types.ModuleType("scripts.lib.cio_outbound_identity")
    fake_ident.subjects_from_tag = lambda tag: []
    fake_ident.tag_text = lambda body: {}
    fake_ident.tag_outbound_event = lambda *a, **k: {"linked": 0}
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_outbound_identity", fake_ident)
    monkeypatch.setattr(sys, "argv", ["backfill_message_identity.py", "--days", "7", "--limit", "3", "--apply"])

    assert mod.main() == 0
    assert len(cur.calls) == 4
    for sql, params in cur.calls:
        assert "operator_message" not in sql          # the excluded type is a parameter now
        assert "'7 days'" not in sql                  # so is the window
        assert sql.count("%s") == len(params)
        assert params[0] == 7 and params[1] == ["operator_message"]
    last_sql, last_params = cur.calls[-1]
    assert "LIMIT %s" in last_sql and last_params[-1] == 3


# --- backfill_hermes_research_provenance (SAFE after allowlist: table/expr only from ALLOWED_TARGETS) -------

def test_hermes_provenance_refuses_unlisted_table_before_sql():
    mod = importlib.import_module("backfill_hermes_research_provenance")
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.backfill(RecordingConn(cur), HOSTILE, "COALESCE(research_type,'manual')", "model_used", {})
    with pytest.raises(ValueError):
        mod._tier_buckets(RecordingConn(cur), "hermes_research_intelligence", HOSTILE, {})
    assert cur.calls == []


def test_hermes_provenance_source_values_are_params():
    mod = importlib.import_module("backfill_hermes_research_provenance")
    cur = RecordingCursor(fetchall_rows=[(HOSTILE,)])
    report = mod.backfill(RecordingConn(cur), *mod.INTEL_TARGET, mod.INTEL_TIER, fallback_intel=True, apply=False)
    assert report["by_tier"] == {"UNMAPPED": {"rows": 0, "distinct_sources": 1}}
    for sql, _params in cur.calls:
        assert HOSTILE not in sql
    count_sql, count_params = cur.calls[1]
    assert "= ANY(%s)" in count_sql and count_params == ([HOSTILE],)


# --- identifier allowlists added in the same function as the f-string -----------------------------------

def test_research_identity_run_refuses_unlisted_table(monkeypatch):
    mod = importlib.import_module("backfill_research_identity")
    monkeypatch.setattr(mod, "_conn", lambda: pytest.fail("connected before the table check"))
    with pytest.raises(ValueError):
        mod.run(HOSTILE, 10, False)


def test_subject_identity_add_columns_refuses_unlisted_table():
    mod = importlib.import_module("backfill_subject_identity")
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.add_columns(cur, HOSTILE, apply=True)
    assert cur.calls == []
