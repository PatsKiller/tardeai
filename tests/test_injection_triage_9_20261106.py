"""Injection triage batch 9: SQL values travel as driver parameters, identifiers only from allowlists.

ANCHOR: INJECTION_TRIAGE_9_20261106

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
    """Records (sql, params); fetchone answers from a queue (then None), fetchall from fixed rows."""

    def __init__(self, fetchone_rows=None, fetchall_rows=None):
        self.calls: list[tuple[str, object]] = []
        self._fetchone = list(fetchone_rows or [])
        self._fetchall_rows = fetchall_rows if fetchall_rows is not None else []
        self.description = [("entity_id",)]
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return list(self._fetchall_rows)

    def close(self):
        pass


class RecordingConn:
    closed = 0

    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass


# --- journal_review_builder (FIX: LIMIT was spliced into SQL text; now a parameter, NULL == no limit) ------

def test_journal_pending_reviews_limit_is_a_param():
    mod = importlib.import_module("journal_review_builder")
    cur = RecordingCursor()
    mod.pending_reviews(cur, 7)
    sql, params = cur.calls[0]
    assert "LIMIT %s" in sql and params == (7,)
    cur = RecordingCursor()
    mod.pending_reviews(cur, None)
    sql, params = cur.calls[0]
    assert params == (None,)  # LIMIT NULL: every row, as the old no-LIMIT text did


def test_journal_pending_reviews_hostile_limit_never_reaches_sql():
    mod = importlib.import_module("journal_review_builder")
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod.pending_reviews(cur, HOSTILE)
    assert cur.calls == []


# --- intelligence_entity_manager (FIX: field names became SET columns; now identifier-checked) ------------

def test_entity_upsert_skips_hostile_column_and_binds_hostile_value():
    mod = importlib.import_module("intelligence_entity_manager")
    cur = RecordingCursor(fetchone_rows=[("E1",)])  # entity exists; recompute SELECT returns nothing
    ok = mod.upsert_entity(RecordingConn(cur), "E1", "ticker",
                           {HOSTILE: 1, "notes": HOSTILE}, source="test")
    assert ok is True
    updates = [(s, p) for s, p in cur.calls if "UPDATE intelligence_entities" in s]
    assert len(updates) == 1
    sql, params = updates[0]
    assert "DROP TABLE" not in sql
    assert "notes = %s" in sql
    assert HOSTILE in params
    assert sql.count("%s") == len(params)


# --- identifier allowlists added in the same function as the f-string -----------------------------------

def test_hybrid_rag_refuses_unlisted_table_before_sql():
    mod = importlib.import_module("hybrid_rag_context_adapter")
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        mod._fetch_candidates(RecordingConn(cur), HOSTILE, [0.0])
    assert cur.calls == []


def test_staleness_count_since_refuses_unlisted_pair_and_accepts_listed():
    mod = importlib.import_module("intel_table_staleness_monitor")
    cur = RecordingCursor(fetchone_rows=[(3,)])
    with pytest.raises(ValueError):
        mod._count_since(cur, HOSTILE, "created_at", 24)
    assert cur.calls == []
    intel, intel_ts = mod.PAIRS[0][0], mod.PAIRS[0][1]
    assert mod._count_since(cur, intel, intel_ts, 24) == 3
    assert len(cur.calls) == 1 and len(cur.calls[0][1]) == 1
