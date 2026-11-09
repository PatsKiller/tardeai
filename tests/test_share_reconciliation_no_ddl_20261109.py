"""LQ-20261107-1686 — share_reconciliation.ensure_tables() asserts no schema on a deployed database.

`ensure_tables` runs from every reconciliation entry point, including the ``*/15`` lane, and issued
four ``CREATE ... IF NOT EXISTS`` statements each time — a name resolution and its lock for a schema
that is already deployed, on a table other writers append to. The catalog answers the question with
no lock, so the statement now runs only for a relation that is genuinely absent.

The real ``ensure_tables`` runs against a fake cursor that answers ``to_regclass`` the way PostgreSQL
does and records every statement. No database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import share_reconciliation as sr  # noqa: E402

_RELATIONS = (
    "position_share_drift",
    "ux_position_share_drift_open_lot",
    "position_reconciliation_log",
    "ix_position_recon_log_lot",
)


class _Catalog:
    def __init__(self, present=_RELATIONS):
        self.present = set(present)
        self.statements: list[str] = []
        self.ddl: list[str] = []


class _FakeCursor:
    def __init__(self, catalog: _Catalog):
        self.catalog = catalog
        self._row = None

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.catalog.statements.append(text)
        if "to_regclass" in text:
            self._row = (params[0] in self.catalog.present,)
            return
        self._row = None
        if text.split(" ", 1)[0].upper() in ("CREATE", "ALTER", "DROP", "TRUNCATE"):
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


def test_a_deployed_database_gets_no_ddl(monkeypatch):
    """THE POINT: the */15 lane must not issue DDL against a schema that is already there."""
    catalog = _Catalog()
    conn = _FakeConn(catalog)
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn, raising=False)

    sr.ensure_tables()

    assert catalog.ddl == [], f"DDL issued on a deployed database: {catalog.ddl}"
    assert conn.commits == 1, "the caller that owns the connection must still commit"


def test_a_missing_table_is_still_created(monkeypatch):
    """Skipping must never mean the schema silently fails to converge."""
    catalog = _Catalog(present=_RELATIONS[1:])
    conn = _FakeConn(catalog)
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn, raising=False)

    sr.ensure_tables()

    assert len(catalog.ddl) == 1, catalog.ddl
    assert "CREATE TABLE IF NOT EXISTS position_share_drift" in catalog.ddl[0]


def test_an_empty_database_gets_every_relation():
    catalog = _Catalog(present=())
    sr.ensure_tables(_FakeCursor(catalog))

    joined = "\n".join(catalog.ddl)
    for relation in _RELATIONS:
        assert f"IF NOT EXISTS {relation}" in joined


def test_a_caller_owned_transaction_is_not_committed():
    """`ensure_tables(cur)` is called inside a caller's transaction; it must not commit it."""
    catalog = _Catalog()
    conn = _FakeConn(catalog)
    sr.ensure_tables(conn.cursor())
    assert catalog.ddl == []
    assert conn.commits == 0, "a caller-supplied cursor must not be committed by ensure_tables"


def test_the_guard_uses_the_shared_catalog_helper():
    assert sr.relation_exists.__module__.removeprefix("scripts.") == "lib.ddl_guard"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
