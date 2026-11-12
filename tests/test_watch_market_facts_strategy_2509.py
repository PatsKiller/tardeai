"""LQ-20261107-2509 (SEV-1 silent failure): watch_market_facts read watchlist_strategy_cards.created_at.

The table has no created_at (symbol is its primary key; it has updated_at), so STRATEGY_SQL failed on every
read since >= 2026-11-02. db_adapter._execute swallows the SQL error and returns None, and load_snapshot
turned None into [] and recorded the read as "ok". A failed read became "Strategy card support missing."

These tests run the real SQL against a disposable PostgreSQL cluster loaded with the production schema
(tests/fixtures/schema_lq2509.sql, schema only) through the real db_adapter._execute, with synthetic rows.
"""
from __future__ import annotations

import ast
import importlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "tests"), str(ROOT / "scripts"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from lib.data_broker import watch_market_facts as mf  # noqa: E402

NOW = datetime(2031, 3, 7, 15, 0, tzinfo=timezone.utc)
SCHEMA_SQL = ROOT / "tests" / "fixtures" / "schema_lq2509.sql"


# ----------------------------------------------------------------------------- disposable cluster
@pytest.fixture(scope="module")
def pg():
    try:
        from support.isolated_pg import pg_bin_dir
        pg_bin_dir()
        import psycopg2  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no PostgreSQL server binaries or psycopg2 ({type(exc).__name__})")
    from support.isolated_pg import IsolatedPostgres
    cluster = IsolatedPostgres()
    try:
        cluster.start()
        cluster.verify_isolated()
        yield cluster
    finally:
        cluster.stop()


@pytest.fixture()
def conn(pg):
    import psycopg2
    e = pg.env()
    c = psycopg2.connect(host=e["DB_HOST"], port=int(e["DB_PORT"]), dbname=e["DB_NAME"], user=e["DB_USER"],
                         password=e["DB_PASSWORD"])
    cur = c.cursor()
    cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    cur.execute(SCHEMA_SQL.read_text())
    # SYNA: a card but no watchlist_items row, so the master view has no row: only the card holds the levels.
    cur.execute("INSERT INTO watchlist_strategy_cards (symbol, strategy_type, support, resistance, updated_at)"
                " VALUES ('SYNA', 'swing_trade', 9, 11, %s)", (NOW,))
    cur.execute("INSERT INTO market_quotes (symbol, price, fetched_at, source) VALUES ('SYNA', 10, %s, 'syn')", (NOW,))
    cur.execute("INSERT INTO ui_prefs (key, value) VALUES (%s, '{\"symbols\": {}}'::jsonb)", (mf.RESISTANCE_KEY,))
    c.commit()
    yield c
    c.close()


@pytest.fixture()
def reader(pg, conn, monkeypatch):
    """The production reader: watch_prospects._db_query wraps db_adapter._execute (swallows, returns None)."""
    for k, v in pg.env().items():
        monkeypatch.setenv(k, v)  # db_adapter never loads .env when DB_PASSWORD is set
    sys.modules.pop("db_adapter", None)
    dba = importlib.import_module("db_adapter")
    monkeypatch.setattr(dba, "ensure_conn", lambda: conn)
    monkeypatch.setattr(dba, "close_thread_conn", lambda: None)
    return lambda sql, params=None, fetch="all": dba._execute(sql, params, fetch=fetch)


def _snap(reader):
    return mf.load_snapshot(reader, ["SYNA"], now=NOW)


# ----------------------------------------------------------------------------- the column
def test_strategy_sql_runs_on_the_real_schema(conn):
    cur = conn.cursor()
    cur.execute(mf.STRATEGY_SQL, (["SYNA"],))
    cols = [d[0] for d in cur.description]
    assert cols == ["symbol", "support", "resistance", "updated_at"] and cur.fetchone()[0] == "SYNA"
    conn.rollback()


def test_master_and_closed_sql_also_run_on_the_real_schema(conn):
    cur = conn.cursor()
    cur.execute(mf.MASTER_SQL, (["SYNA"],))
    cur.execute(mf.PREF_SQL, (mf.RESISTANCE_KEY,))
    conn.rollback()


def test_a_card_only_symbol_shows_the_card_levels_with_the_update_time(reader, caplog):
    caplog.set_level(logging.WARNING, logger=mf.__name__)
    raw = _snap(reader)
    assert raw["read_status"] == {"quotes": "ok", "master": "ok", "strategy": "ok", "closed": "ok"}
    facts = mf.view(raw, "SYNA", now=NOW)
    for kind, value in (("support", 9), ("resistance", 11)):
        f = facts[kind]
        assert f["value"] == value and f["source"] == "watchlist_strategy_cards"
        assert datetime.fromisoformat(f["as_of"]) == NOW and f["as_of_basis"] == "strategy card updated_at"
        assert "Strategy-card update time" in f["reason"] and f["unreadable_sources"] == []
    assert not [r for r in caplog.records if "read unavailable" in r.getMessage()]


# ----------------------------------------------------------------------------- the failure is visible
def test_a_swallowed_strategy_failure_is_unknown_and_logged_never_missing(reader, conn, caplog):
    """The real production failure mode: a column the SQL selects is gone, _execute returns None."""
    conn.cursor().execute("ALTER TABLE watchlist_strategy_cards RENAME COLUMN updated_at TO updated_at_x")
    conn.commit()
    caplog.set_level(logging.WARNING, logger=mf.__name__)
    raw = _snap(reader)
    assert raw["read_status"]["strategy"] == "unavailable" and raw["read_status"]["master"] == "ok"
    s = mf.view(raw, "SYNA", now=NOW)["support"]
    assert s["value"] is None and s["freshness"] == "UNKNOWN" and s["freshness"] != "MISSING"
    assert "Strategy card support read unavailable." in s["reason"]
    assert s["unreadable_sources"] == ["watchlist_strategy_cards"]
    assert s["source_label"] == "Reference unknown: source read unavailable"
    assert any("strategy read unavailable" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("source", ["quotes", "master", "strategy", "closed"])
def test_a_none_from_any_reader_is_unavailable_not_empty(source, caplog):
    """None is db_adapter's failure signal; an empty list is 'no rows'. Neither may read as the other."""
    def db(sql, params=None, fetch="all"):
        name = ("quotes" if "market_quotes" in sql else "master" if "watchlist_symbol_master" in sql
                else "strategy" if "watchlist_strategy_cards" in sql else "closed")
        return None if name == source else []
    caplog.set_level(logging.WARNING, logger=mf.__name__)
    raw = mf.load_snapshot(db, ["SYNA"], now=NOW)
    assert raw["read_status"][source] == "unavailable"
    assert all(v != "unavailable" for k, v in raw["read_status"].items() if k != source)
    assert any(f"{source} read unavailable" in r.getMessage() for r in caplog.records)


def test_empty_rows_are_still_missing_not_unknown():
    raw = mf.load_snapshot(lambda sql, params=None, fetch="all": [], ["SYNA"], now=NOW)
    s = mf.view(raw, "SYNA", now=NOW)["support"]
    assert s["freshness"] == "MISSING" and s["unreadable_sources"] == [] and "missing" in s["reason"]


def test_db_adapter_execute_still_signals_failure_with_none():
    """The contract this fix relies on: _execute's except path returns None (it never re-raises)."""
    tree = ast.parse((ROOT / "scripts" / "db_adapter.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_execute")
    handlers = [h for t in ast.walk(fn) if isinstance(t, ast.Try) for h in t.handlers]
    last = fn.body[-1].handlers[-1].body[-1] if isinstance(fn.body[-1], ast.Try) else None
    assert handlers and isinstance(last, ast.Return) and isinstance(last.value, ast.Constant) and last.value.value is None
