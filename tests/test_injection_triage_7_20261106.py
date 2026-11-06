"""Injection triage batch 7: interpolated SQL is constants, placeholders or regex-checked identifiers only.

ANCHOR: INJECTION_TRIAGE_7_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair, and the real functions are driven
through it. A hostile value must arrive in params (or be refused before any SQL runs), never in SQL text.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.description = [("id",), ("source_type",), ("source_id",), ("title",), ("embedding",)]
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RecordingConn:
    def __init__(self):
        self.cur = RecordingCursor()
        self.autocommit = False

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_embedding_sample_source_types_travel_as_params():
    import embedding_ab_baseline as E

    conn = RecordingConn()
    E.get_sample_docs(conn, limit=7, source_types=[HOSTILE, "news"])
    (sql, params), = conn.cur.calls
    assert HOSTILE not in sql
    assert "source_type IN (%s,%s)" in sql
    assert list(params) == [HOSTILE, "news", 7]


def test_directive_flag_reconcile_sql_holds_no_value():
    import directive_promotion as D

    conn = RecordingConn()
    plan = {"clear": [{"id": 1, "symbol": HOSTILE}]}
    out = D.apply_directive_watch_flag_reconcile(conn, plan, backup_path=_tmp_backup())
    assert out["attempted"] == 1
    sql, params = conn.cur.calls[-1]
    assert HOSTILE not in sql
    assert params["ids"] == [1]
    assert params["creators"] == list(D.OPERATOR_DIRECTIVE_CREATORS)


def _tmp_backup():
    import tempfile
    return Path(tempfile.mkdtemp()) / "flag_backup.jsonl"


def test_finviz_savepoint_names_are_identifier_safe_for_hostile_screener_ids():
    import finviz_screener_runner as F

    for sid in (HOSTILE, "", None, 'a" ; DROP', "x" * 200, "bond_etf_income"):
        for prefix in ("sp_scr", "sp_mem"):
            name = F._sp_name(prefix, sid)
            assert F._SAVEPOINT_RE.fullmatch(name), name
    assert not F._SAVEPOINT_RE.fullmatch("sp_scr_x; DROP TABLE t")
    assert not F._SAVEPOINT_RE.fullmatch("sp_scr_")


def test_ensure_m2_refuses_a_hostile_database_name_before_any_sql(monkeypatch):
    import ensure_m2_test_database as M

    def _no_connect(*a, **k):
        raise AssertionError("connected for a refused name")

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", _no_connect)
    assert M.main(["--name", 'm2_shadow_test"; DROP DATABASE trade_ai;--']) == 2
    assert M.main(["--name", HOSTILE]) == 2
