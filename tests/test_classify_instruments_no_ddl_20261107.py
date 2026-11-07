"""classify-instruments must never take a table lock on symbol_profiles (queue item 1, 2026-11-07).

The lane used to run FOUR ``ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS`` statements on every real
run. An ADD COLUMN takes an ACCESS EXCLUSIVE lock on the whole table while ``db_adapter`` sets
``lock_timeout = 3s``, so one concurrent transaction on symbol_profiles kills the run — the exact death
etf-analyst-enrich suffered on 2026-11-07 07:00 ET:

    $ pg log 2026-11-07 07:00:09.375 EST [731183] trade_ai@trade_ai
    ERROR:  canceling statement due to lock timeout
    STATEMENT:  ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric

These tests pin the replacement: the columns are a MIGRATION, the run only reads ``information_schema``,
and a database without a column stops with exit 2 naming the migration instead of retrying DDL.

Hermetic: fake connection, synthetic universe/holdings, no DB, no network, no repo file write.
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

import classify_instruments as ci  # noqa: E402

MIGRATION_PATH = ROOT / "migrations" / "2026_11_07_symbol_profiles_instrument_cols.sql"
# The four columns, named here so this file still COLLECTS against the pre-fix script (which had no such
# constant): a red run must fail on the defect, not on an ImportError the reader has to interpret.
EXPECTED_COLUMNS = ("instrument_type", "direction_hint", "expense_ratio", "quote_type")
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE", "DROP", "GRANT")
_UNIVERSE = {"instruments": [{"symbol": "TQQQ", "type": "inverse_etf", "direction": "short"}]}
_PROFILES = [("AAPL", "Technology", "Apple Inc"), ("SPY", "Large Blend", "SPDR S&P 500 ETF Trust")]


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


def _conn(have=EXPECTED_COLUMNS):
    def responder(sql, _p):
        if "information_schema.columns" in sql:
            return {"all": [(c,) for c in have]}
        if "quote_type FROM symbol_profiles" in sql:
            return {"all": [("SPY", "ETF")]}
        if "FROM symbol_profiles" in sql:
            return {"all": list(_PROFILES)}
        return None

    return _Conn(responder)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))
    uni = tmp_path / "etf_fund_universe.json"
    uni.write_text(json.dumps(_UNIVERSE), encoding="utf-8")
    monkeypatch.setattr(ci, "UNIVERSE", uni)
    # The real run writes this file; keep the test out of the repository tree.
    monkeypatch.setattr(ci, "OUT", tmp_path / "instrument_types_latest.json")


def _receipt(tmp_path):
    p = tmp_path / "data" / "runtime" / "classify-instruments_last.json"
    return json.loads(p.read_text()) if p.exists() else None


def _ok_upsert(record):
    def _up(cur, symbol, values, **_k):
        record.append((symbol, values))
        return types.SimpleNamespace(rows_written=1, rows_rejected=0)

    return _up


# ── the migration is the DDL's home, and it defines exactly the columns the script needs ──────────────


def test_migration_file_exists_and_adds_the_required_columns():
    assert MIGRATION_PATH.exists(), "the migration MIGRATION names must exist"
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "ALTER TABLE symbol_profiles" in body
    assert tuple(ci.PROFILE_COLUMNS) == EXPECTED_COLUMNS
    for column in EXPECTED_COLUMNS:
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {column}\b", body), column
    assert ci.MIGRATION.endswith(MIGRATION_PATH.name)


# ── the run never issues DDL ──────────────────────────────────────────────────────────────────────────


def test_run_path_source_contains_no_alter_table():
    assert "ALTER TABLE" not in inspect.getsource(ci._run)
    assert "ALTER TABLE" not in inspect.getsource(ci.main)
    assert "ALTER TABLE" not in inspect.getsource(ci.check_columns)


def test_real_run_issues_no_write_statement_at_all(monkeypatch, tmp_path):
    conn, written = _conn(), []
    monkeypatch.setattr(ci, "_get_conn", lambda: conn)
    monkeypatch.setattr(ci, "upsert_profile", _ok_upsert(written))
    rc, summary = ci._run(["--no-fetch"], dry_run=False)
    assert rc == 0 and summary["profile_rows_updated"] == len(written) > 0
    assert conn.writes() == [], conn.writes()
    assert any("information_schema.columns" in s for s in conn.sql)
    # the run really did its job, and the runtime file it promises exists
    assert ci.OUT.exists() and json.loads(ci.OUT.read_text())["types"]["TQQQ"] == "inverse_etf"


def test_check_columns_reads_information_schema_only():
    conn = _conn()
    ci.check_columns(conn.cursor())
    assert len(conn.sql) == 1 and "information_schema.columns" in conn.sql[0]
    assert conn.writes() == []


# ── a database without the columns stops, names the migration, and writes a failed receipt ───────────


@pytest.mark.parametrize("have", [
    (), ("instrument_type",), ("direction_hint", "expense_ratio"),
    tuple(c for c in EXPECTED_COLUMNS if c != "quote_type"),
])
def test_check_columns_raises_missing_columns_naming_the_migration(have):
    with pytest.raises(ci.MissingColumns) as ei:
        ci.check_columns(_conn(have).cursor())
    assert "migrations/2026_11_07_symbol_profiles_instrument_cols.sql" in str(ei.value)


def test_missing_columns_exit_2_and_no_write_attempt(tmp_path, monkeypatch, capsys):
    conn = _conn(have=())

    def _no_write(*_a, **_k):
        raise AssertionError("a missing migration must not reach the upsert")

    monkeypatch.setattr(ci, "_get_conn", lambda: conn)
    monkeypatch.setattr(ci, "upsert_profile", _no_write)

    assert ci.main([]) == 2
    out = capsys.readouterr().out
    assert "2026_11_07_symbol_profiles_instrument_cols.sql" in out
    r = _receipt(tmp_path)
    assert r["status"] == "failed" and r["ok_at"] is None and r["exit"] == 2
    assert r["skipped_reasons"] == {"schema_migration_missing": 1}
    assert conn.writes() == []
    assert not ci.OUT.exists()  # a refused run does not leave a "latest" file behind


# ── the dry run tells the truth about what a real run would do ───────────────────────────────────────


def test_dry_run_reports_the_migration_and_promises_no_write(monkeypatch, capsys):
    monkeypatch.setattr(ci, "_get_conn", lambda: _conn(have=("instrument_type",)))
    assert ci.main(["--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out.strip())

    # a dry run never writes a receipt and never writes the runtime file
    assert not ci.OUT.exists()
    assert report["instrument_columns_missing"] == ["direction_hint", "expense_ratio", "quote_type"]
    assert report["required_migration"] == ci.MIGRATION
    assert report["would_write"] == {}


def test_dry_run_with_every_column_present_promises_only_the_row_writes(monkeypatch, capsys):
    monkeypatch.setattr(ci, "_get_conn", lambda: _conn())
    assert ci.main(["--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out.strip())
    assert report["required_migration"] is None
    assert report["instrument_columns_present"] == sorted(EXPECTED_COLUMNS)
    assert report["would_write"]["symbol_profiles_rows"] == report["classified"] > 0
    assert not ci.OUT.exists()


def test_dry_run_session_is_read_only(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(ci, "_get_conn", lambda: conn)
    assert ci.main(["--dry-run"]) == 0
    assert conn.readonly is True
