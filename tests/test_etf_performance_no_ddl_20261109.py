"""LQ-20261107-1686 — the symbol_profiles enrich lane asserts its columns without a lock.

``etf_performance_enrich.enrich()`` ran ``ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS`` for
all four of its columns on every real run. An ADD COLUMN asks for an **ACCESS EXCLUSIVE** lock whether
or not the column is already there — the same defect as the ticket's two named writers, and the same
table the ticket names as related (LQ-84 / 119 / 1373). ``symbol_profiles`` is read by the watchlist
API and written by every enrich lane, so the lock had readers to block.

``preview()`` already answered the question (`would_run_ddl`) with an information_schema read; the
write path now asks the same question instead of assuming.

The real ``enrich()`` runs against a fake connection whose cursor answers the catalog read the way
PostgreSQL would and records every statement. No database, no Finviz cache, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import etf_performance_enrich as ep  # noqa: E402

_ALL = tuple(c for c, _ in ep._PERF_COLS)


class _Catalog:
    def __init__(self, present=_ALL):
        self.present = set(present)
        self.statements: list[str] = []
        self.ddl: list[str] = []


class _FakeCursor:
    def __init__(self, catalog: _Catalog):
        self.catalog = catalog
        self._rows: list[tuple] = []

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.catalog.statements.append(text)
        if "information_schema.columns" in text:
            wanted = set(params[0]) if params else set()
            self._rows = [(c,) for c in sorted(self.catalog.present & wanted)]
            return
        self._rows = []
        if text.split(" ", 1)[0].upper() in ("CREATE", "ALTER", "DROP", "TRUNCATE"):
            self.catalog.ddl.append(text)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, catalog: _Catalog):
        self.cursor_obj = _FakeCursor(catalog)
        self.commits = 0

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _run(monkeypatch, catalog: _Catalog) -> _FakeConn:
    conn = _FakeConn(catalog)
    # an empty target list: the DDL block runs, then the lane returns before any cache or row write
    monkeypatch.setattr(ep, "_get_conn", lambda: conn)
    monkeypatch.setattr(ep, "_target_symbols", lambda cur: [])
    ep.enrich()
    return conn


def test_an_up_to_date_table_issues_no_ddl(monkeypatch):
    """THE POINT. Steady state must take no exclusive lock on symbol_profiles."""
    catalog = _Catalog()
    _run(monkeypatch, catalog)

    assert catalog.ddl == [], f"DDL issued against an up-to-date table: {catalog.ddl}"
    assert sum("information_schema.columns" in s for s in catalog.statements) == 1


def test_a_missing_column_runs_exactly_that_one_alter(monkeypatch):
    """Skipping must never mean the schema silently fails to converge."""
    catalog = _Catalog(present=("ytd_return_pct", "dividend_yield_pct", "perf_updated_at"))
    _run(monkeypatch, catalog)

    assert len(catalog.ddl) == 1, catalog.ddl
    assert "ADD COLUMN IF NOT EXISTS ttm_dividend" in catalog.ddl[0]


def test_a_fresh_table_adds_every_column(monkeypatch):
    catalog = _Catalog(present=())
    _run(monkeypatch, catalog)

    joined = "\n".join(catalog.ddl)
    for column in _ALL:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in joined


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
