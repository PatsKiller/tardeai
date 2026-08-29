"""A closed, rolled-over account is not an unexplained gap.

`fidelity_rollover_ira` closed 2026-07-17 and rolled into
`schwab_rollover_ira`, but kept `reported_total_value` 566,439.39 as of
2026-07-16 — the day before the transfer. The repricer classified that stale
snapshot `UNEXPLAINED`, so it read on every pass as a missing half-million.

The pre-rollover backup settles it: Fidelity 566,439.39 + Schwab 583,116.93,
and Schwab now holds 1,164,151.51. The money moved. Adding the residual to cash
would double-count the rollover — which is why these tests pin cash *not*
moving as hard as they pin the reclassification.
"""
from __future__ import annotations

import copy

import pytest

from scripts.portfolio_repricer import _recalc_totals

ROW_SUM = 630_784.82
RESIDUAL = 566_439.39


@pytest.fixture()
def book():
    cash = [
        {"symbol": "CASH", "account": "schwab_rollover_ira", "is_cash": True,
         "market_value": 585_917.80},
        {"symbol": "CASH", "account": "schwab_taxable", "is_cash": True,
         "market_value": 37_894.31},
        {"symbol": "CASH", "account": "alpaca_taxable_live", "is_cash": True,
         "market_value": 5_000.00},
        {"symbol": "CASH", "account": "schwab_roth", "is_cash": True,
         "market_value": 1_472.71},
        {"symbol": "CASH", "account": "moomoo_taxable_live", "is_cash": True,
         "market_value": 500.00},
    ]
    return {
        "as_of": "2026-08-29",
        "holdings": cash + [
            {"symbol": "SCHD", "account": "schwab_rollover_ira",
             "market_value": 351_408.81, "cost_basis": 300_000.0, "is_cash": False},
        ],
        "portfolio_totals": {},
        "account_summaries": {
            "schwab_rollover_ira": {}, "schwab_taxable": {}, "schwab_roth": {},
            "alpaca_taxable_live": {}, "moomoo_taxable_live": {},
            "fidelity_rollover_ira": {
                "source": "manual_fidelity_reflection",
                "reported_total_value": RESIDUAL,
                "reported_total_as_of": "2026-07-16",
                "closed_at": "2026-07-17T03:19:26.775227+00:00",
                "status": "closed_rolled_to_schwab",
                "rolled_to": "schwab_rollover_ira",
                "holdings_count": 0,
            },
        },
    }


def test_closed_rolled_account_is_explained_not_unexplained(book):
    _recalc_totals(book)
    a = book["account_summaries"]["fidelity_rollover_ira"]
    assert a["residual_quality"] == "EXPLAINED_ROLLED_OVER"
    assert "schwab_rollover_ira" in a["residual_explanation"]
    assert "not cash" in a["residual_explanation"].lower()


def test_the_residual_is_never_added_to_cash(book):
    """The whole point. Adding it would double-count the July rollover."""
    _recalc_totals(book)
    t = book["portfolio_totals"]
    assert t["total_cash"] == ROW_SUM
    assert t["total_cash_source"] == "position_rows"
    assert t["total_cash"] != ROW_SUM + RESIDUAL


def test_the_closed_account_contributes_nothing_to_total_value(book):
    _recalc_totals(book)
    assert book["account_summaries"]["fidelity_rollover_ira"]["total_value"] == 0


def test_an_open_account_with_drift_is_still_unexplained(book):
    """The reclassification must not swallow a genuine reconciliation gap."""
    a = book["account_summaries"]["fidelity_rollover_ira"]
    a.pop("closed_at")
    a.pop("status")
    a.pop("rolled_to")
    _recalc_totals(book)
    assert a["residual_quality"] == "UNEXPLAINED"


def test_closed_without_a_destination_stays_unexplained(book):
    """Closed but not rolled anywhere is a real question, not an explanation."""
    book["account_summaries"]["fidelity_rollover_ira"].pop("rolled_to")
    _recalc_totals(book)
    assert book["account_summaries"]["fidelity_rollover_ira"][
        "residual_quality"] == "UNEXPLAINED"


def test_residual_stays_non_security_and_uninjected(book):
    _recalc_totals(book)
    a = book["account_summaries"]["fidelity_rollover_ira"]
    assert a["residual_class"] == "NON_SECURITY"
    assert a["reconciliation_residual_usd"] == RESIDUAL
