"""LQ-20261107-2509: agent_watchlist_engine.get_symbol_strategy ordered by watchlist_strategy_cards.created_at.

The column does not exist, so every call raised, was swallowed and returned "unknown": the
SECTOR_CORRELATION_ALERT in agent_event_router could never fire, and the connection leaked.
Real SQL on a disposable PostgreSQL cluster with the production schema; synthetic rows only.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "tests"), str(ROOT / "scripts"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

SCHEMA_SQL = ROOT / "tests" / "fixtures" / "schema_lq2509.sql"


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
def engine(pg, monkeypatch):
    import psycopg2
    e = pg.env()

    def connect():
        return psycopg2.connect(host=e["DB_HOST"], port=int(e["DB_PORT"]), dbname=e["DB_NAME"], user=e["DB_USER"],
                                password=e["DB_PASSWORD"])

    c = connect()
    cur = c.cursor()
    cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    cur.execute(SCHEMA_SQL.read_text())
    for sym in ("SYNA", "SYNB", "SYNC"):
        cur.execute("INSERT INTO watchlist_strategy_cards (symbol, strategy_type) VALUES (%s, 'swing_trade')", (sym,))
    c.commit()
    c.close()
    mod = importlib.import_module("agent_watchlist_engine")
    opened = []

    def tracked():
        conn = connect()
        opened.append(conn)
        return conn

    monkeypatch.setattr(mod, "_get_conn", tracked)  # never the .env-reading production connect
    mod._opened = opened
    yield mod
    for conn in opened:
        conn.close()


def _break_schema(pg):
    import psycopg2
    e = pg.env()
    c = psycopg2.connect(host=e["DB_HOST"], port=int(e["DB_PORT"]), dbname=e["DB_NAME"], user=e["DB_USER"],
                         password=e["DB_PASSWORD"])
    c.cursor().execute("ALTER TABLE watchlist_strategy_cards RENAME COLUMN strategy_type TO strategy_type_x")
    c.commit()
    c.close()


def test_the_card_strategy_is_read_from_the_real_schema(engine):
    assert engine.get_symbol_strategy("syna") == "swing_trade"
    assert all(c.closed for c in engine._opened)


def test_three_same_strategy_symbols_raise_the_sector_alert(engine):
    alert = engine.detect_sector_correlation(["SYNA", "SYNB", "SYNC"])
    assert alert and alert["event_type"] == "SECTOR_CORRELATION_ALERT" and alert["count"] == 3
    assert sorted(alert["symbols"]) == ["SYNA", "SYNB", "SYNC"]


def test_a_failed_read_is_logged_and_closes_the_connection(engine, pg, capsys):
    _break_schema(pg)
    assert engine.get_symbol_strategy("SYNA") == "unknown"
    err = capsys.readouterr().err
    assert "get_symbol_strategy(SYNA) read failed" in err and "UndefinedColumn" in err
    assert engine._opened and all(c.closed for c in engine._opened)
