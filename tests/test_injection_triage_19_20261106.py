"""Injection triage batch 19: SQL f-strings no longer carry values into the SQL text.

ANCHOR: INJECTION_TRIAGE_19_20261106

Hermetic: a fake cursor records every (sql, params) pair; no database, no network.
- validate_classification_rule_engine.main binds each table name as a parameter (FIX).
- trade_strategy_classifier keeps its symbol filter a literal ANY(%s) clause, so a hostile
  symbol reaches params and never the SQL text (SAFE-marked line, behaviour pinned).
"""
import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

HOSTILE = "x'; DROP TABLE t;--"


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        pass

    def close(self):
        pass


def test_validate_classification_binds_table_names(monkeypatch, tmp_path):
    cur = FakeCursor()
    fake_pg = types.ModuleType("psycopg2")
    fake_pg.connect = lambda **kw: FakeConn(cur)
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    # strategy_rule_engine would reach a real DB; make every later section fail closed.
    monkeypatch.setitem(sys.modules, "strategy_rule_engine", types.ModuleType("strategy_rule_engine"))
    mod = importlib.import_module("validate_classification_rule_engine")
    (tmp_path / ".env").write_text("DB_PASSWORD=x\n")
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "RESULTS", [])

    def no_api(path):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(mod, "api_get", no_api)
    monkeypatch.setattr(sys, "argv", ["validate"])
    mod.main()

    schema_calls = [(s, p) for s, p in cur.calls if "information_schema.tables" in s]
    assert len(schema_calls) == 11
    for sql, params in schema_calls:
        assert sql == "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=%s"
        assert isinstance(params, tuple) and len(params) == 1
    assert schema_calls[0][1] == ("strategy_registry",)
    assert schema_calls[-1][1] == ("marl_training_episodes",)


def test_strategy_classifier_symbols_arrive_as_params():
    mod = importlib.import_module("trade_strategy_classifier")
    for fn in (mod._query_strategy_backtest_trades, mod._query_trades_view):
        cur = FakeCursor()
        fn(cur, 5, symbols=[HOSTILE])
        sql, params = cur.calls[-1]
        assert HOSTILE not in sql
        assert "= ANY(%s)" in sql and "LIMIT %s" in sql
        assert list(params) == [[HOSTILE], 5]

        cur = FakeCursor()
        fn(cur, 7)
        sql, params = cur.calls[-1]
        assert "ANY(%s)" not in sql
        assert list(params) == [7]
