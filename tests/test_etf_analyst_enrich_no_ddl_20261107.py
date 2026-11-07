"""etf-analyst-enrich must never take a table lock on symbol_profiles (LQ-20261107-105).

The lane used to run ``ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS`` on every real run. An
ADD COLUMN takes an ACCESS EXCLUSIVE lock on the whole table while ``db_adapter`` sets ``lock_timeout =
3s``, so one concurrent transaction on symbol_profiles killed the run:

    $ pg log 2026-11-07 07:00:09.375 EST [731183] trade_ai@trade_ai
    ERROR:  canceling statement due to lock timeout
    STATEMENT:  ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric

These tests pin the replacement: the columns are a MIGRATION, the run only reads ``information_schema``,
and a database without the columns stops with exit 2 naming the migration instead of retrying DDL.

Hermetic: fake connections, no DB, no network.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import etf_analyst_enrich as eae  # noqa: E402

MIGRATION_PATH = ROOT / "migrations" / "2026_11_07_symbol_profiles_analyst_cols.sql"
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE", "DROP", "GRANT")


class _Cursor:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 1
        self._one, self._all = (0,), []

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.sql.append(norm)
        res = (self.conn.responder(norm, params) if self.conn.responder else None) or {}
        self._one, self._all = res.get("one", (0,)), res.get("all", [])
        self.rowcount = res.get("rowcount", 1)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, responder=None):
        self.responder = responder
        self.sql, self.commits, self.rollbacks, self.readonly = [], 0, 0, False

    def cursor(self, *a, **k):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass

    def set_session(self, readonly=False, **_k):
        self.readonly = readonly

    def writes(self):
        return [s for s in self.sql if s.split(" ", 1)[0].upper() in _WRITE_VERBS]


def _conn(have=("analyst_basis", "analyst_look_through_pct"), etfs=(("SPY", "etf", None),)):
    def responder(sql, _p):
        if "information_schema.columns" in sql:
            return {"all": [(c,) for c in have]}
        if "FROM symbol_profiles" in sql:
            return {"all": list(etfs)}
        if "count(DISTINCT" in sql:
            return {"one": (7,)}
        if "SELECT DISTINCT upper(symbol) FROM yahoo_analyst_targets_history" in sql:
            return {"all": []}
        return None

    return _Conn(responder)


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))


def _receipt(tmp_path, lane="etf-analyst-enrich"):
    p = tmp_path / "data" / "runtime" / f"{lane}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


def _yf_stub(info):
    return types.SimpleNamespace(Ticker=lambda _s: types.SimpleNamespace(info=info, funds_data=None))


# ── the migration is the DDL's home, and it defines exactly the columns the script needs ──────────────


def test_migration_file_exists_and_adds_the_required_columns():
    assert MIGRATION_PATH.exists(), "the migration MIGRATION names must exist"
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "ALTER TABLE symbol_profiles" in body
    for column in eae.REQUIRED_COLUMNS:
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {column}\b", body), column
    assert eae.MIGRATION.endswith(MIGRATION_PATH.name)


# ── the run never issues DDL ──────────────────────────────────────────────────────────────────────────


def test_enrich_source_contains_no_alter_table():
    assert "ALTER TABLE" not in inspect.getsource(eae.enrich)
    assert "ALTER TABLE" not in inspect.getsource(eae.preview)


def test_real_run_issues_no_write_statement_at_all(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(eae, "_get_conn", lambda: conn)
    monkeypatch.setattr(eae, "upsert_profile", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "yfinance", _yf_stub({}))
    res = eae.enrich()
    assert res["ok"] is True
    assert conn.writes() == [], conn.writes()
    assert any("information_schema.columns" in s for s in conn.sql)


def test_check_columns_reads_information_schema_only():
    conn = _conn()
    eae.check_columns(conn.cursor())
    assert len(conn.sql) == 1 and "information_schema.columns" in conn.sql[0]
    assert conn.writes() == []


# ── a database without the columns stops, names the migration, and writes a failed receipt ───────────


@pytest.mark.parametrize("have", [(), ("analyst_basis",), ("analyst_look_through_pct",)])
def test_check_columns_raises_missing_columns_naming_the_migration(have):
    with pytest.raises(eae.MissingColumns) as ei:
        eae.check_columns(_conn(have).cursor())
    assert "migrations/2026_11_07_symbol_profiles_analyst_cols.sql" in str(ei.value)


def test_missing_columns_exit_2_and_no_yfinance_call(tmp_path, monkeypatch, capsys):
    conn = _conn(have=())

    def _no_network(*_a, **_k):
        raise AssertionError("a missing migration must not start the fetch passes")

    monkeypatch.setattr(eae, "_get_conn", lambda: conn)
    monkeypatch.setattr(eae, "upsert_profile", _no_network)
    monkeypatch.setitem(sys.modules, "yfinance", _no_network)

    assert eae.main([]) == 2
    out = capsys.readouterr().out
    assert "2026_11_07_symbol_profiles_analyst_cols.sql" in out
    r = _receipt(tmp_path)
    assert r["status"] == "failed" and r["ok_at"] is None and r["exit"] == 2
    assert r["skipped_reasons"] == {"schema_migration_missing": 1}
    assert conn.writes() == []


# ── the dry run tells the truth about what a real run would do ───────────────────────────────────────


def test_dry_run_reports_the_migration_and_promises_no_table_write(monkeypatch, capsys):
    monkeypatch.setattr(eae, "_get_conn", lambda: _conn(have=("analyst_basis",)))
    monkeypatch.setattr(eae, "upsert_profile", lambda *a, **k: None)
    assert eae.main(["--dry-run"]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    report = json.loads(line.split(" ", 1)[1])
    assert report["summary"]["analyst_columns_missing"] == ["analyst_look_through_pct"]
    assert report["summary"]["required_migration"] == eae.MIGRATION
    assert report["would_write"] == []
    assert not [w for w in report["would_write"] if "ALTER" in w]


def test_dry_run_with_every_column_present_lists_only_row_writes(monkeypatch, capsys):
    monkeypatch.setattr(eae, "_get_conn", lambda: _conn())
    monkeypatch.setattr(eae, "upsert_profile", lambda *a, **k: None)
    assert eae.main(["--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1].split(" ", 1)[1])
    assert report["summary"]["required_migration"] is None
    assert len(report["would_write"]) == 2
    assert not [w for w in report["would_write"] if "ALTER" in w or "DDL" in w]
