"""Item 118 — cost-basis as_of on the coverage card.

The three dates are genuinely different on the live book (basis 08-14,
positions 08-26, prices 08-28), so a reader who assumes "now" is wrong by up to
two weeks. Stamping them is the whole point.
"""
from __future__ import annotations

from scripts.lib.cio_command_center import build_office_coverage
from scripts.lib.cio_investment_product import collect_holdings_thesis_coverage

HOLDINGS = {
    "as_of": "2026-08-26",
    "last_repriced": "2026-08-28 16:45:01 ET",
    "reconciled_at": "2026-08-14T21:25:43.617032+00:00",
    "holdings": [
        {"symbol": "SCHD", "market_value": 365_694.75,
         "cost_basis": 12_687.73, "cost_basis_source": "csv_lot"},
        {"symbol": "BAH", "market_value": 673.83, "cost_basis_source": "broker_api"},
    ],
}


def test_coverage_carries_three_distinct_dates():
    cov = collect_holdings_thesis_coverage(holdings=HOLDINGS, root=None)
    assert cov["positions_as_of"] == "2026-08-26"
    assert cov["cost_basis_as_of"].startswith("2026-08-14")
    assert cov["priced_as_of"].startswith("2026-08-28")
    assert len({cov["positions_as_of"], cov["cost_basis_as_of"], cov["priced_as_of"]}) == 3


def test_cost_basis_sources_are_named():
    cov = collect_holdings_thesis_coverage(holdings=HOLDINGS, root=None)
    assert cov["cost_basis_sources"] == ["broker_api", "csv_lot"]


def test_the_card_surfaces_them():
    cov = collect_holdings_thesis_coverage(holdings=HOLDINGS, root=None)
    card = build_office_coverage(holdings_thesis_coverage=cov)
    assert card["cost_basis_as_of"].startswith("2026-08-14")
    assert card["positions_as_of"] == "2026-08-26"
    assert card["priced_as_of"].startswith("2026-08-28")


def test_missing_dates_are_none_not_invented():
    cov = collect_holdings_thesis_coverage(holdings={"holdings": []}, root=None)
    assert cov["cost_basis_as_of"] is None
    assert cov["positions_as_of"] is None
