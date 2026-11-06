"""Injection triage batch 17: interpolated SQL became driver parameters or quoted identifiers.

ANCHOR: INJECTION_TRIAGE_17_20261106

Hermetic: every database is a fake cursor that records (sql, params); no connection is opened.
A hostile value must arrive in params or inside a quoted sql.Identifier, never in the SQL text.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

HOSTILE = "x'; DROP TABLE t;--"


class _Cur:
    def __init__(self, fetch_one=(0, None), rows=()):
        self.calls: list[tuple] = []
        self._one, self._rows = fetch_one, list(rows)
        self.description = [("c",)]
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, params=None):
        self.calls.append((q, params))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.autocommit = True

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _fake_db_adapter(monkeypatch, cur):
    mod = types.ModuleType("db_adapter")
    mod.get_connection = lambda: _Conn(cur)
    monkeypatch.setitem(sys.modules, "db_adapter", mod)


def _sql_parts(q):
    """(literal SQL text, identifier strings) of a str or a psycopg2.sql composition."""
    if isinstance(q, str):
        return [q], []
    if isinstance(q, sql.Composed):
        texts, idents = [], []
        for part in q.seq:
            t, i = _sql_parts(part)
            texts += t
            idents += i
        return texts, idents
    if isinstance(q, sql.Identifier):
        return [], list(q.strings)
    if isinstance(q, sql.SQL):
        return [q.string], []
    raise AssertionError(f"unexpected SQL object {type(q)!r}")


def test_scalp_outcome_learning_days_is_a_parameter(monkeypatch):
    import scalp_outcome_learning as sol

    cur = _Cur()
    _fake_db_adapter(monkeypatch, cur)
    sol.learn(days=45)
    q, params = cur.calls[0]
    assert "%s * INTERVAL '1 day'" in q and "45" not in q
    assert params == (45,)

    cur2 = _Cur()
    _fake_db_adapter(monkeypatch, cur2)
    out = sol.learn(days=HOSTILE)  # int() refuses it before any SQL runs
    assert all(HOSTILE not in str(c[0]) for c in cur2.calls)
    assert out["sample_size"] == 0


def test_sec_form4_windows_are_parameters(monkeypatch):
    import sec_form4_source_maturity as m

    cur = _Cur(fetch_one=(3, None))
    _fake_db_adapter(monkeypatch, cur)
    monkeypatch.setattr(m, "SOURCE_FRESH_DAYS", 11)
    monkeypatch.setattr(m, "CATALYST_RELEVANT_DAYS", 13)
    m.build(30)
    windowed = [c for c in cur.calls if "INTERVAL" in c[0]]
    assert [c[1] for c in windowed] == [(11,), (13,)]
    assert all("11" not in c[0] and "13" not in c[0] for c in windowed)


def test_seed_phase2e_tables_are_identifiers_and_limit_a_parameter(monkeypatch):
    import seed_phase2e_shadow_from_qwen3_test as seed

    cur = _Cur(fetch_one=(0,))
    monkeypatch.setattr(seed, "get_conn", lambda: _Conn(cur))
    monkeypatch.setattr(sys, "argv", ["seed", "--apply", "--source-table", HOSTILE,
                                      "--target-table", "shadow_t", "--limit", "7"])
    seed.main()
    insert = [c for c in cur.calls if "INSERT" in " ".join(_sql_parts(c[0])[0])]
    assert len(insert) == 1 and insert[0][1] == (7,)
    for q, _params in cur.calls:
        texts, idents = _sql_parts(q)
        assert all(HOSTILE not in t for t in texts)
    assert any(HOSTILE in _sql_parts(q)[1] for q, _ in cur.calls)


def test_session34_table_and_column_are_identifiers(monkeypatch, tmp_path):
    import session34_fix_covered_call_schema as s34

    class _DictCur(_Cur):
        def fetchone(self):
            last = self.calls[-1][0]
            if isinstance(last, str) and "information_schema" in last:
                return {"column_name": HOSTILE, "data_type": "numeric", "character_maximum_length": None}
            return {"cnt": 0}

    cur = _DictCur()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(s34, "get_db_conn", lambda: _Conn(cur))
    monkeypatch.setattr(sys, "argv", ["s34", "--table", HOSTILE, "--column", HOSTILE,
                                      "--apply", "--skip-preflight"])
    s34.main()
    assert cur.calls[0][1] == (HOSTILE, HOSTILE)  # the lookup was already parameterized
    for q, _params in cur.calls[1:]:
        texts, idents = _sql_parts(q)
        assert all(HOSTILE not in t for t in texts)
        assert HOSTILE in idents
    alters = [_sql_parts(q)[1] for q, _ in cur.calls if "ALTER TABLE" in " ".join(_sql_parts(q)[0])]
    assert [HOSTILE + "_low", HOSTILE + "_high"] == alters[1][1:]


def test_scalp_universe_refuses_an_unsafe_config_identifier():
    import scalp_shadow_logger as ssl

    cur = _Cur()
    u = {"source_table": HOSTILE, "symbol_column": "symbol", "time_column": "scanned_at",
         "float_column": "float_mm", "price_column": "price"}
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        ssl.resolve_universe_detail(_Conn(cur), {"universe": u}, float_lookup=lambda s, u: {})
    assert cur.calls == []
