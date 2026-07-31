"""Cash holdings must never receive equity enrichment or stop-placement semantics.

Deterministic unit tests — no broker, no production writes.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_api_v2(monkeypatch, holdings_doc, enrichment=None, technical=None):
    """Import api_v2 with minimal filesystem / DB stubs for portfolio_holdings()."""
    import api_v2

    api_v2 = importlib.reload(api_v2)

    def fake_load_json(path):
        name = Path(path).name if not isinstance(path, str) else Path(str(path)).name
        if name == "holdings.json":
            return holdings_doc
        if name == "ticker_enrichment_cache.json":
            return enrichment or {}
        if name == "technical_snapshot.json":
            return technical or {}
        if name == "finviz_quote_cache.json":
            return {}
        if name == "action_signals.json":
            return {"signals": []}
        if name == "dividend_calendar.json":
            return {"payers": []}
        if name == "snapshot_index.json":
            return []
        return {}

    monkeypatch.setattr(api_v2, "_load_json", fake_load_json)
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    return api_v2


def _cash_holdings_doc():
    return {
        "as_of": "2026-07-31",
        "last_repriced": "2026-07-31T12:00:00+00:00",
        "portfolio_totals": {"total_value": 1_250_000.0, "day_change": 0.0},
        "holdings": [
            {
                "symbol": "CASH",
                "account": "schwab_rollover_ira",
                "is_cash": True,
                "price": 1.0,
                "current_price": 1.0,
                "shares": 1000.0,
                "market_value": 536_822.73,
                "day_change": 0.0,
                "day_change_pct": 0.0,
                "name": "Cash & Cash Investments",
            },
            {
                "symbol": "CASH",
                "account": "alpaca_taxable_live",
                "is_cash": True,
                "price": 1.0,
                "current_price": 1.0,
                "shares": 5000.0,
                "market_value": 5000.0,
                "day_change": 0.0,
                "day_change_pct": 0.0,
                "name": "Cash & Cash Investments",
            },
            {
                "symbol": "CASH",
                "account": "moomoo_taxable_live",
                "is_cash": True,
                "price": 1.0,
                "current_price": 1.0,
                "shares": 500.0,
                "market_value": 500.0,
                "day_change": 0.0,
                "day_change_pct": 0.0,
                "name": "Cash & Cash Investments",
            },
            {
                "symbol": "V",
                "account": "schwab_rollover_ira",
                "is_cash": False,
                "price": 280.0,
                "current_price": 280.0,
                "shares": 10.0,
                "market_value": 2800.0,
                "name": "Visa",
            },
        ],
    }


def test_cash_rows_stay_unit_price_and_skip_equity_enrichment(monkeypatch):
    # Poisoned enrichment cache for symbol CASH (the live regression).
    poisoned = {
        "CASH": {
            "symbol": "CASH",
            "rsi": 50.27,
            "pe": 12.3,
            "pb": 1.4,
            "analyst_rating": "Buy",
            "perf_ytd_pct": 8.1,
            "company": "DAIHEN Contaminant",
        },
        "V": {"symbol": "V", "rsi": 55.0, "pe": 30.0},
    }
    api = _load_api_v2(monkeypatch, _cash_holdings_doc(), enrichment=poisoned)
    out = api.portfolio_holdings()
    holds = out["holdings"]
    cash = [h for h in holds if h.get("is_cash") or str(h.get("symbol")).upper() == "CASH"]
    assert len(cash) == 3
    accounts = {h["account"] for h in cash}
    assert accounts == {"schwab_rollover_ira", "alpaca_taxable_live", "moomoo_taxable_live"}
    for h in cash:
        assert h["price"] == 1.0
        assert h["current_price"] == 1.0
        assert h["price_source"] == "cash_unit"
        assert h["day_change"] == 0.0
        assert h["day_change_pct"] == 0.0
        assert h.get("rsi") is None
        assert h.get("pe") is None
        assert h.get("pb") is None
        assert h.get("analyst_rating") is None
        assert h.get("perf_ytd_pct") is None
        assert h.get("company") in (None, "")
        assert h.get("pi_score") is None
        assert h.get("fib") is None
        assert h.get("data_available") is False
        assert "Cash" in str(h.get("analysis_note") or "")
        # Market values preserved (not price * shares contamination).
        assert h["market_value"] in (536_822.73, 5000.0, 500.0)

    equities = [h for h in holds if not h.get("is_cash")]
    assert any(h["symbol"] == "V" for h in equities)


def test_cash_asset_type_boundary_without_is_cash_flag(monkeypatch):
    doc = {
        "portfolio_totals": {"total_value": 10_000.0},
        "holdings": [
            {
                "symbol": "USD",
                "account": "test_acct",
                "asset_type": "cash",
                "price": 1.0,
                "current_price": 1.0,
                "shares": 100.0,
                "market_value": 100.0,
            }
        ],
    }
    api = _load_api_v2(monkeypatch, doc, enrichment={"USD": {"rsi": 99, "pe": 5}})
    out = api.portfolio_holdings()
    row = out["holdings"][0]
    assert row["is_cash"] is True
    assert row["price"] == 1.0
    assert row["rsi"] is None
    assert row["pe"] is None


def test_ui_source_has_cash_and_unverifiable_guards():
    """Static guards for the fail-closed UI contract (no browser required)."""
    row_model = (ROOT / "apps/command-center-v3/src/lib/holdingsRowModel.ts").read_text()
    table = (ROOT / "apps/command-center-v3/src/components/HoldingsTableView.tsx").read_text()
    protect = (ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx").read_text()
    pill = (ROOT / "apps/command-center-v3/src/components/StopKindPill.tsx").read_text()

    assert "protectionState: 'PROTECTED' | 'NO_STOP' | 'UNVERIFIABLE' | 'CASH'" in row_model
    assert "isCashHolding" in row_model
    assert "Do not place duplicate stop" in row_model
    assert "needsVerification" in row_model
    assert "need stop placement" in table
    assert "verification required" in table
    assert "holdings-placement-count" in table
    assert "holdings-verification-count" in table
    assert "VERIFY STOPS — BROKER VERIFICATION REQUIRED" in protect
    assert "Do not place duplicate stop" in protect
    assert "CASH — no protective stop" in protect
    assert "!brokerReadDegraded" in protect or "&& !brokerReadDegraded" in protect
    assert "CASH:" in pill
    assert "cash holding — protective stops do not apply" in pill
