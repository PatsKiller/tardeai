"""Wave 2 slice 01: held equities get CURRENT or UNAVAILABLE thesis. No fake thesis."""
from __future__ import annotations

from scripts.lib.cio_investment_product import collect_holdings_thesis_coverage


def test_held_without_living_thesis_is_unavailable_not_invented():
    cov = collect_holdings_thesis_coverage(
        holdings={"holdings": [{"symbol": "ZZZX", "quantity": 1, "asset_type": "equity"}]},
        root=None,
    )
    assert cov["held_n"] == 1
    row = cov["items"][0]
    assert row["symbol"] == "ZZZX"
    assert row["thesis_status"] == "UNAVAILABLE"
    assert row["why_owned_or_watched"] is None
    assert row["thesis_status_reason"]
    assert cov["no_fake_thesis"] is True
    assert cov["unavailable_n"] == 1
    assert cov["current_n"] == 0


def test_cash_and_cusip_are_not_held_equities():
    cov = collect_holdings_thesis_coverage(
        holdings={"holdings": [
            {"symbol": "CASH", "quantity": 100},
            {"symbol": "12507E201", "quantity": 10},
        ]},
        root=None,
    )
    assert cov["held_n"] == 0
    assert cov["items"] == []


def test_living_thesis_is_current(monkeypatch):
    def _fake(symbol, *, root=None):
        return {
            "has_current_symbol_thesis": True,
            "thesis_state": "CURRENT",
            "thesis_summary": "Income ballast.",
            "why_owned_or_watched": "Income ballast.",
        }

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol",
        _fake,
    )
    cov = collect_holdings_thesis_coverage(
        holdings={"holdings": [{"symbol": "SCHD", "quantity": 10, "asset_type": "etf"}]},
        root=None,
    )
    assert cov["items"][0]["thesis_status"] == "CURRENT"
    assert cov["items"][0]["why_owned_or_watched"] == "Income ballast."
    assert cov["current_n"] == 1
