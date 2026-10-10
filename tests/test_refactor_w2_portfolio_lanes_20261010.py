"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V3 -- portfolio data lanes.

- technicals_gap_backfill.py (cron:L470): --dry-run lists the missing symbols on a READ ONLY session and
  returns before yfinance, the ticker_snapshot_daily upsert and the --alert send; a real run writes
  technicals-gap-backfill_last.json; no-data symbols are a finding (exit 0).
- classify_instruments.py (cron:L504): --dry-run runs no ALTER TABLE, no yfinance quoteType fetch, no
  symbol_profiles upsert and no instrument_types_latest.json write; a real run writes
  classify-instruments_last.json (ok_at only on success).
Hermetic: fake db_adapter / yfinance modules, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP")


class FakeConn:
    """Tuple rows; records every statement."""

    def __init__(self, responder=None, fail_on=None):
        self.responder = responder or (lambda sql, params: [])
        self.fail_on = fail_on
        self.sql: list[str] = []
        self.calls: list = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(str(sql).split())
                conn.sql.append(flat)
                if conn.fail_on and flat.upper().startswith(conn.fail_on):
                    raise RuntimeError("simulated write failure")
                self._rows = [tuple(r) for r in (conn.responder(flat, params) or [])]

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return C()

    def writes(self):
        return [s for s in self.sql if s.upper().startswith(WRITE_PREFIXES)]

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def set_session(self, **kw):
        self.calls.append(("set_session", kw))

    def close(self):
        self.calls.append("close")


class _Hist:
    def __init__(self, closes):
        self.closes = closes

    def __len__(self):
        return len(self.closes)

    def __getitem__(self, key):
        return types.SimpleNamespace(tolist=lambda: list(self.closes))


class _YF:
    def __init__(self, closes=None, info=None):
        self.closes = closes or []
        self.info = info or {}
        self.calls = 0

    def Ticker(self, sym):  # noqa: N802 -- yfinance API name
        self.calls += 1
        return types.SimpleNamespace(history=lambda period: _Hist(self.closes), info=self.info)


def _receipt(state, name):
    p = state / "data" / "runtime" / f"{name}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"w2v3_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── technicals_gap_backfill (cron:L470) ───────────────────────────────────────


@pytest.fixture
def tgb(monkeypatch):
    mod = _load("technicals_gap_backfill")
    conn = FakeConn(lambda sql, params: [("AAA", None, None)] if "DISTINCT ON (symbol)" in sql else [])
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    alert = mock.Mock()
    monkeypatch.setattr(mod, "_alert", alert)
    return mod, conn, alert


def test_gap_dry_run_reaches_no_fetch_upsert_or_alert(tgb, state, monkeypatch):
    mod, conn, alert = tgb
    yf = _YF(closes=[1.0] * 30)
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    assert mod.main(["--symbols", "AAA", "--alert", "--dry-run"]) == 0
    assert yf.calls == 0 and conn.writes() == [] and "commit" not in conn.calls
    assert not alert.called and ("set_session", {"readonly": True}) in conn.calls
    assert _receipt(state, "technicals-gap-backfill") is None


def test_gap_real_run_fills_and_writes_receipt(tgb, state, monkeypatch):
    mod, conn, alert = tgb
    monkeypatch.setitem(sys.modules, "yfinance", _YF(closes=[float(i) for i in range(1, 40)]))
    assert mod.main(["--symbols", "AAA", "--alert"]) == 0
    assert any(s.startswith("INSERT INTO ticker_snapshot_daily") for s in conn.writes())
    assert not alert.called
    rec = _receipt(state, "technicals-gap-backfill")
    assert rec["status"] == "ok" and rec["summary"]["filled"] == 1


def test_gap_no_data_symbols_are_a_finding_not_a_failure(tgb, state, monkeypatch):
    mod, _, alert = tgb
    monkeypatch.setitem(sys.modules, "yfinance", _YF(closes=[]))
    assert mod.main(["--symbols", "AAA", "--alert"]) == 0
    assert alert.called  # existing --alert behaviour, unchanged
    rec = _receipt(state, "technicals-gap-backfill")
    assert rec["status"] == "ok" and rec["summary"]["no_data"] == 1


def test_gap_failed_write_is_failed_receipt(tgb, state, monkeypatch):
    mod, conn, _ = tgb
    conn.fail_on = "INSERT"
    monkeypatch.setitem(sys.modules, "yfinance", _YF(closes=[float(i) for i in range(1, 40)]))
    with pytest.raises(RuntimeError):
        mod.main(["--symbols", "AAA"])
    assert _receipt(state, "technicals-gap-backfill")["status"] == "failed"


# ── classify_instruments (cron:L504) ──────────────────────────────────────────


def _ci_rows(sql, params):
    if sql.startswith("SELECT upper(symbol), sector, description_1s"):
        return [("AAA", "Technology", "Makes chips"), ("SPYX", "Fund", "index fund")]
    if "quote_type IS NULL" in sql:
        return [("AAA",)]
    return []


@pytest.fixture
def ci(monkeypatch, tmp_path):
    conn = FakeConn(_ci_rows)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    mod = _load("classify_instruments")
    upsert = mock.Mock(return_value=types.SimpleNamespace(rows_written=1, rows_rejected=0))
    monkeypatch.setattr(mod, "upsert_profile", upsert)
    monkeypatch.setattr(mod, "OUT", tmp_path / "instrument_types_latest.json")
    monkeypatch.setattr(mod, "ROOT", tmp_path)  # no holdings.json: holdings step skipped
    return mod, conn, upsert


def test_classify_dry_run_no_alter_fetch_upsert_or_file(ci, state, monkeypatch):
    mod, conn, upsert = ci
    yf = _YF(info={"quoteType": "ETF"})
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    assert mod.main(["--dry-run"]) == 0
    assert conn.writes() == [] and "commit" not in conn.calls
    assert ("set_session", {"readonly": True}) in conn.calls
    assert yf.calls == 0 and not upsert.called and not mod.OUT.exists()
    assert _receipt(state, "classify-instruments") is None


def test_classify_real_run_writes_profiles_file_and_receipt(ci, state, monkeypatch):
    mod, conn, upsert = ci
    monkeypatch.setitem(sys.modules, "yfinance", _YF(info={"quoteType": "EQUITY"}))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert mod.main([]) == 0
    assert any(s.startswith("ALTER TABLE symbol_profiles") for s in conn.writes())
    assert upsert.called and mod.OUT.exists()
    rec = _receipt(state, "classify-instruments")
    assert rec["status"] == "ok" and rec["summary"]["profile_rows_updated"] == upsert.call_count


def test_classify_failure_is_failed_receipt(ci, state):
    mod, conn, _ = ci
    conn.fail_on = "ALTER"
    with pytest.raises(RuntimeError):
        mod.main(["--no-fetch"])
    assert _receipt(state, "classify-instruments")["status"] == "failed"
