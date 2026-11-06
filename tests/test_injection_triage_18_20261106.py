"""Injection triage batch 18: values reach SQL as driver parameters, identifiers are checked or quoted.

ANCHOR: INJECTION_TRIAGE_18_20261106

Hermetic: a fake cursor records (sql, params); no database, no network. Each test drives the real
function with a hostile value and shows it lands in params (or is refused), never in the SQL text.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
# CI's plain shards do not install psycopg2; this line routes the file to the Postgres shard (scripts/lib/ci_shards.py).
pytest.importorskip("psycopg2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class FakeCursor:
    def __init__(self, rows=None, description=None):
        self.calls: list[tuple[object, object]] = []
        self._rows = rows or []
        self.description = description or []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


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


def test_stop_drift_advisory_window_is_a_bound_param():
    import stop_drift_alert as m

    cur = FakeCursor()
    m._load_recent_advisories(cur, days=37)
    sql, params = cur.calls[0]
    assert params == (37,)
    assert "37" not in sql
    assert "%s * interval '1 day'" in sql


def test_sweep_terminal_statuses_are_a_bound_list(monkeypatch):
    import sweep_stale_paper_proposals as m

    cur = FakeCursor()
    monkeypatch.setattr(m, "get_conn", lambda: FakeConn(cur))
    monkeypatch.setattr(m, "TERMINAL_STATUSES", {"EXPIRED", HOSTILE})
    monkeypatch.setattr(sys, "argv", ["sweep", "--dry-run", "--limit", "5"])
    m.main()
    sql, params = cur.calls[0]
    assert HOSTILE not in sql
    assert "status <> ALL(%s)" in sql
    assert sorted(params[0]) == sorted(["EXPIRED", HOSTILE])
    assert params[1] == 5


def test_volume_profile_universe_identifiers_are_quoted_not_spliced():
    from psycopg2 import sql as psql

    import symbol_volume_profile_builder as m

    cur = FakeCursor()
    cfg = {"universe": {"symbol_column": "symbol", "source_table": HOSTILE, "time_column": "scanned_at",
                        "float_column": "float_mm", "float_mm_max": 30, "lookback_days": 21}}
    m.resolve_universe(FakeConn(cur), cfg)
    query, params = cur.calls[0]
    assert isinstance(query, psql.Composed)
    assert params == [21, 30.0]
    literal_text = "".join(p.string for p in query.seq if isinstance(p, psql.SQL))
    assert HOSTILE not in literal_text
    idents = [p for p in query.seq if isinstance(p, psql.Identifier)]
    assert any(HOSTILE in p.strings for p in idents)


def test_social_scout_replay_window_is_a_bound_param(monkeypatch):
    import social_scout_replay_report as m

    cur = FakeCursor(rows=[], description=[("symbol",)])
    fake = types.ModuleType("db_adapter")
    fake.get_connection = lambda: FakeConn(cur)
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    out = m.build(days=12)
    assert out["ok"] is True
    sql, params = cur.calls[0]
    assert params == (12,)
    assert "12" not in sql


def test_freshness_helpers_refuse_identifiers_outside_the_registry():
    import system_freshness_monitor as m

    cur = FakeCursor(rows=[(0,)])
    with pytest.raises(ValueError):
        m._count_since(cur, HOSTILE, 24)
    with pytest.raises(ValueError):
        m._age_hours(cur, "news_articles", ts_col=HOSTILE)
    assert cur.calls == []
    m._count_since(cur, "news_articles", 24)
    assert cur.calls[0][0] == "SELECT count(*) FROM news_articles WHERE created_at > %s"


def test_taxonomy_ddl_refuses_unknown_table():
    import taxonomy_tagger as m

    cur = FakeCursor()
    with pytest.raises(ValueError):
        m._ensure_columns(cur, HOSTILE)
    assert cur.calls == []
