"""Alpha Vantage phantom budget spend (API_OVERLAP_CONSOLIDATION Q5, operator-approved 2026-10-10).

Measured: api_budget_ledger counted ~4,650 "alphavantage" calls/week with 0 real requests, because
catalyst_enrichment._fetch_alpha_vantage called api_budget.spend() BEFORE checking the
ENABLE_ALPHA_VANTAGE_CATALYST flag, and api_budget.spend() incremented the ledger before comparing to
the cap (the ledger read "exhausted 23/22" daily).

Fakes only: no network, no database. The SQL semantics were also run against a scratch Postgres 17
(not the live DB) for the PR evidence.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import api_budget  # noqa: E402
import catalyst_enrichment as ce  # noqa: E402


def _spy_budget(monkeypatch, allow=True):
    calls = []
    mod = types.ModuleType("api_budget")

    def spend(provider, n=1):
        calls.append(provider)
        return allow

    mod.spend = spend
    monkeypatch.setitem(sys.modules, "api_budget", mod)
    return calls


def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no HTTP request expected")
    monkeypatch.setattr(ce.requests, "get", boom)


def test_flag_off_records_no_budget_spend(monkeypatch):
    calls = _spy_budget(monkeypatch)
    _no_network(monkeypatch)
    monkeypatch.setenv("ENABLE_ALPHA_VANTAGE_CATALYST", "false")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "k")
    assert ce._fetch_alpha_vantage("AAPL") == []
    assert calls == [], "a disabled fetcher must not count a call in api_budget_ledger"


def test_missing_key_records_no_budget_spend(monkeypatch):
    calls = _spy_budget(monkeypatch)
    _no_network(monkeypatch)
    monkeypatch.setenv("ENABLE_ALPHA_VANTAGE_CATALYST", "true")
    monkeypatch.setattr(ce, "_env", lambda k, d="": {"ENABLE_ALPHA_VANTAGE_CATALYST": "true"}.get(k, d))
    assert ce._fetch_alpha_vantage("AAPL") == []
    assert calls == []


def test_enabled_path_reads_the_owner_store_and_spends_nothing(monkeypatch):
    # 2026-10-10 (AV owner): the slot no longer sends its own request, so it no longer spends from
    # api_budget either. The one Alpha Vantage budget is the owner's (lib/alpha_vantage_owner.py).
    calls = _spy_budget(monkeypatch, allow=False)
    _no_network(monkeypatch)
    monkeypatch.setattr(ce, "_env", lambda k, d="": {"ENABLE_ALPHA_VANTAGE_CATALYST": "true",
                                                      "ALPHA_VANTAGE_API_KEY": "k"}.get(k, d))
    from lib.data_broker import news_sentiment as ns
    monkeypatch.setattr(ns, "_load", lambda base: None)
    assert ce._fetch_alpha_vantage("AAPL") == []  # empty store -> nothing, and no request
    assert calls == []


class _Cur:
    def __init__(self, row):
        self.sql, self.row = [], row

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.cur = _Cur(row)

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def test_spend_checks_cap_before_incrementing(monkeypatch):
    conn = _Conn(None)  # the guarded upsert returned no row: the call did not fit
    monkeypatch.setattr(api_budget, "_conn", lambda: conn)
    monkeypatch.setenv("API_BUDGET_ALPHAVANTAGE", "22")
    assert api_budget.spend("alphavantage") is False
    upsert, params = conn.cur.sql[-1]
    assert "api_budget_ledger.calls + EXCLUDED.calls <=" in upsert, "the increment must be conditional on the cap"
    assert 22 in params


def test_spend_within_cap_returns_true(monkeypatch):
    conn = _Conn((5,))
    monkeypatch.setattr(api_budget, "_conn", lambda: conn)
    assert api_budget.spend("alphavantage") is True
