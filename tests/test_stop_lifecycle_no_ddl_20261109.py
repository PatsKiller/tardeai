"""LQ-20261107-1686 — the stop-lifecycle snapshot writer takes no table lock to assert its schema.

``scripts/stop_lifecycle_monitor.py::_persist()`` runs on every scan, and the scan runs from
``stop_health_check`` (``*/10 9-16``) and from the 45 s-cached ``/api/v2/stops/lifecycle``. It used to
issue ``CREATE TABLE IF NOT EXISTS stop_lifecycle`` plus four ``ALTER TABLE ... ADD COLUMN IF NOT
EXISTS`` before writing its snapshot; each ALTER asked for an ACCESS EXCLUSIVE lock on the table to
assert a column that already existed. On 2026-11-09 14:18–15:19 ET that contributed to 124 lock
timeouts and 5 deadlocks against a 3 s ``lock_timeout``.

These tests drive the real ``_persist`` against a fake connection whose cursor answers catalog reads
the way PostgreSQL would and records every statement. One synthetic record; no database, no broker.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import stop_lifecycle_monitor as slm  # noqa: E402

_COLUMNS = ("trail_offset", "price_source", "price_as_of", "price_stale")


class _Catalog:
    def __init__(self, table: bool = True, columns=_COLUMNS):
        self.table = table
        self.columns = set(columns)
        self.statements: list[str] = []
        self.ddl: list[str] = []


class _FakeCursor:
    def __init__(self, catalog: _Catalog):
        self.catalog = catalog
        self._row = None

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.catalog.statements.append(text)
        if "information_schema.columns" in text:
            table, column = params
            self._row = (1,) if (table == "stop_lifecycle" and column in self.catalog.columns) else None
            return
        if "to_regclass" in text:
            self._row = (params[0] == "stop_lifecycle" and self.catalog.table,)
            return
        self._row = None
        if text.split(" ", 1)[0].upper() in ("CREATE", "ALTER"):
            self.catalog.ddl.append(text)

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, catalog: _Catalog):
        self.cursor_obj = _FakeCursor(catalog)
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _record() -> dict:
    return {
        "account": "ZQ_ACCOUNT", "symbol": "ZQAAA", "broker": "zqbroker", "order_id": "ZQ-ORDER-1",
        "order_type": "stop", "status": "working", "stop_price": 10.0, "qty": 5, "held_qty": 5,
        "current_price": 12.0, "proximity_pct": 16.7, "coverage": "full", "lifecycle": "working",
        "health": "ok", "flags": [], "trail_offset": None, "price_source": "zq",
        "price_as_of": "2026-11-09 14:00:00 ET", "price_stale": False,
    }


def _run(monkeypatch, catalog: _Catalog) -> _FakeConn:
    conn = _FakeConn(catalog)
    stub = types.ModuleType("db_adapter")
    stub._get_conn = lambda: conn
    monkeypatch.setitem(sys.modules, "db_adapter", stub)
    slm._persist([_record()])
    return conn


def test_an_up_to_date_table_writes_only_the_snapshot(monkeypatch):
    catalog = _Catalog()
    conn = _run(monkeypatch, catalog)

    assert catalog.ddl == [], f"DDL issued against an up-to-date table: {catalog.ddl}"
    # Five catalog reads, then the snapshot write itself — which must always happen.
    assert sum("DELETE FROM stop_lifecycle" in s for s in catalog.statements) == 1
    assert sum("INSERT INTO stop_lifecycle" in s for s in catalog.statements) == 1
    assert conn.commits == 1


def test_a_missing_column_runs_exactly_that_one_alter(monkeypatch):
    catalog = _Catalog(columns=("price_source", "price_as_of", "price_stale"))
    _run(monkeypatch, catalog)

    assert len(catalog.ddl) == 1, catalog.ddl
    assert "ADD COLUMN IF NOT EXISTS trail_offset" in catalog.ddl[0]
    assert sum("INSERT INTO stop_lifecycle" in s for s in catalog.statements) == 1


def test_a_missing_table_is_created_and_its_additive_columns_added(monkeypatch):
    """A fresh database: the CREATE body carries the base columns, the four ALTERs the rest."""
    catalog = _Catalog(table=False, columns=())
    _run(monkeypatch, catalog)

    joined = "\n".join(catalog.ddl)
    assert "CREATE TABLE IF NOT EXISTS stop_lifecycle" in joined
    for column in _COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in joined
    assert sum("INSERT INTO stop_lifecycle" in s for s in catalog.statements) == 1


def test_the_guard_uses_the_shared_catalog_helper():
    assert slm.relation_exists.__module__.removeprefix("scripts.") == "lib.ddl_guard"
    assert slm.column_exists.__module__.removeprefix("scripts.") == "lib.ddl_guard"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
