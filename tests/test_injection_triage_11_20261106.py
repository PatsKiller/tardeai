"""Injection triage batch 11: SQL values travel as driver parameters, identifiers only from allowlists.

ANCHOR: INJECTION_TRIAGE_11_20261106

Hermetic. No database server: a fake cursor records every (sql, params) pair, and the real functions are driven
through it (the coordination ledger runs on a throwaway sqlite file). A hostile value must arrive as a quoted
identifier or in params, or be refused before any SQL runs; it never lands raw in SQL text.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    """Records (sql, params); answers fetchone with a fixed one-column row."""

    def __init__(self, fetchone_row=(0,)):
        self.calls: list[tuple[object, object]] = []
        self._row = fetchone_row

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingConn:
    def __init__(self, cur):
        self._cur = cur
        self.autocommit = True

    def cursor(self, *a, **k):
        return self._cur

    def rollback(self):
        pass


# --- memory_shadow_projector.apply_schema (FIX: current_database() was spliced into GRANT text) -------------

def test_grant_quotes_a_hostile_database_name_as_an_identifier(monkeypatch, tmp_path):
    psycopg2_sql = pytest.importorskip("psycopg2.sql")
    from scripts.lib import memory_shadow_projector as mod

    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(mod, "SQL_PATH", schema)
    monkeypatch.setattr(mod, "destructive_reset_permitted", lambda conn, is_production=False: False)
    cur = RecordingCursor(fetchone_row=(HOSTILE,))
    mod.apply_schema(RecordingConn(cur))

    grants = [sql for sql, _ in cur.calls if isinstance(sql, psycopg2_sql.Composable)]
    assert len(grants) == 2
    for grant in grants:
        parts = grant.seq
        idents = [p for p in parts if isinstance(p, psycopg2_sql.Identifier)]
        assert [i.string for i in idents][0] == HOSTILE  # the hostile name is an Identifier, quoted by the driver
        literal_text = "".join(p.string for p in parts if isinstance(p, psycopg2_sql.SQL))
        assert HOSTILE not in literal_text
        assert "DROP TABLE" not in literal_text
    assert {g.seq[3].string for g in grants} == {"tradeai_memory_shadow_writer", "tradeai_memory_shadow_reader"}


def test_shadow_count_refuses_a_table_outside_its_allowlist():
    from scripts.lib import memory_shadow_projector as mod

    cur = RecordingCursor(fetchone_row=(7,))
    assert mod._count(RecordingConn(cur), "memory_fact_version") == 7
    with pytest.raises(ValueError):
        mod._count(RecordingConn(cur), HOSTILE)
    assert len(cur.calls) == 1  # the refused name never reached execute


# --- redeploy_phase_a_db._next_version (table name now checked against a fixed allowlist) -------------------

def test_next_version_allowlists_the_table_and_parameterizes_the_event():
    from scripts.lib import redeploy_phase_a_db as mod

    cur = RecordingCursor(fetchone_row=(3,))
    assert mod._next_version(cur, "redeploy_exposure_loss", 42) == 3
    sql, params = cur.calls[0]
    assert "FROM redeploy_exposure_loss WHERE deploy_event_id=%s" in sql
    assert params == (42,)
    with pytest.raises(ValueError):
        mod._next_version(cur, HOSTILE, 42)
    assert len(cur.calls) == 1


# --- n8n_coordination_ledger._add_columns (identifiers now matched against a strict regex) -------------------

def test_ledger_add_columns_refuses_hostile_identifiers(tmp_path):
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    ledger = CoordinationLedger(tmp_path / "ledger.sqlite3")
    try:
        ledger._add_columns("runs", {"injection_probe": "TEXT"})
        cols = {r["name"] for r in ledger._conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "injection_probe" in cols
        for bad in ({"c": HOSTILE}, {HOSTILE: "TEXT"}):
            with pytest.raises(ValueError):
                ledger._add_columns("runs", bad)
        with pytest.raises(ValueError):
            ledger._add_columns(HOSTILE, {"c": "TEXT"})
        tables = {r[0] for r in ledger._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "runs" in tables and "t" not in tables
    finally:
        ledger.close()
