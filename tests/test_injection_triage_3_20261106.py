"""Injection triage batch 3 (2026-11-06): SQL built by string formatting now binds values as driver params.

ANCHOR: INJECTION_TRIAGE_3_20261106

Hermetic: a fake cursor records (sql, params); no database, no network. A hostile value
(`x'; DROP TABLE t;--`) must never land in literal SQL text. Identifiers that cannot be
parameters travel as psycopg2.sql.Identifier, which quotes and escapes them.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class FakeCursor:
    def __init__(self, description=None, rows=None, fetchone=(0,)):
        self.calls: list[tuple[object, object]] = []
        self.description = description or [("n",)]
        self._rows = rows or []
        self._one = fetchone
        self.connection = types.SimpleNamespace(rollback=lambda: None)

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one

    def close(self):
        pass


class FakeConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _literal_sql_parts(query) -> list[str]:
    """Every piece of literal SQL text in a str or psycopg2.sql composable (identifiers excluded)."""
    if isinstance(query, str):
        return [query]
    if isinstance(query, sql.SQL):
        return [query.string]
    if isinstance(query, sql.Composed):
        out: list[str] = []
        for part in query.seq:
            out.extend(_literal_sql_parts(part))
        return out
    return []  # sql.Identifier / sql.Literal: quoted by the driver


def _identifiers(query) -> list[str]:
    if isinstance(query, sql.Identifier):
        return list(query.strings)
    if isinstance(query, sql.Composed):
        out: list[str] = []
        for part in query.seq:
            out.extend(_identifiers(part))
        return out
    return []


def test_table_readers_audit_quotes_a_hostile_table_name(monkeypatch, capsys):
    import audit_table_readers_without_writers as mod

    cur = FakeCursor()
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: FakeConn(cur)))
    monkeypatch.setattr(mod, "real_tables", lambda c: {HOSTILE})
    monkeypatch.setattr(mod, "scan", lambda: ({HOSTILE: {"reader.py"}}, {}))
    monkeypatch.setattr(sys, "argv", ["audit_table_readers_without_writers.py", "--json"])
    assert mod.main() == 0
    (query, params), = cur.calls
    assert all(HOSTILE not in part for part in _literal_sql_parts(query))
    assert _identifiers(query) == [HOSTILE]


def test_archive_probe_rows_quotes_hostile_column_names(monkeypatch, tmp_path):
    import archive_trade_closed_probe_rows as mod

    cur = FakeCursor(description=[("id",), (HOSTILE,)], rows=[(7, "v")], fetchone=(1,))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(get_connection=lambda: FakeConn(cur)))
    monkeypatch.setattr(mod.pp, "load_closed_config", lambda: {"test_accounts": ["health"]})
    monkeypatch.setattr(mod, "ROOT", tmp_path)  # backup JSON lands in the temp tree
    assert mod.main(["--apply"]) == 0
    insert = [(q, p) for q, p in cur.calls if not isinstance(q, str)]
    assert len(insert) == 1
    query, params = insert[0]
    assert all(HOSTILE not in part for part in _literal_sql_parts(query))
    assert _identifiers(query) == ["id", HOSTILE, "id", HOSTILE]
    assert params == ("health probe row counted as a trade (reconciliation 2026-10-05)", [7])


@pytest.mark.parametrize("all_time,days", [(True, 14), (False, 3)])
def test_screener_find_window_is_a_bound_param(monkeypatch, all_time, days):
    import auto_research as mod

    cur = FakeCursor()
    monkeypatch.setattr(mod, "_get_conn", lambda: FakeConn(cur))
    assert mod._screener_find_candidates(all_time=all_time, days=days) == []
    query, params = cur.calls[0]
    assert "portfolio_intelligence_events" in query
    assert "INTERVAL '1 day'" in query and f"'{days} days'" not in query
    assert params == (all_time, days)


def test_screener_find_window_rejects_a_hostile_days_value(monkeypatch):
    import auto_research as mod

    cur = FakeCursor()
    monkeypatch.setattr(mod, "_get_conn", lambda: FakeConn(cur))
    with pytest.raises(ValueError):
        mod._screener_find_candidates(all_time=False, days=HOSTILE)
    assert cur.calls == []
