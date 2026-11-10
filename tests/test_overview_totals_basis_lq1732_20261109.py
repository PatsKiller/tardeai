"""LQ-20261107-1732: the served account and portfolio totals are the positions store's basis.

Measured 2026-11-09 19:03 ET on the live page: every account total and the portfolio total stood
above ``positions_current`` (the numbers-truth audit's truth, tolerance $1) — the portfolio by
336.88. The page's figures were not the store's: ``cio_truth.overview_payload`` republishes every
total as the sum of the holdings rows **re-marked at a live quote on the read**. 295.10 of that
336.88 was one row — a line carrying a frozen backup quote 1000x the broker's own mark.

These tests pin the published basis, not the re-mark: the store's own figures stand under the
totals' names, the live re-mark is published beside them by name with its delta, and the total
contract (LQ-1611) is rebuilt so the header, its by-account sum and its rows are one basis. A
document with no broker values keeps the old behaviour and names it.

Synthetic rows only; no live store, database or network.
"""
from __future__ import annotations

from scripts.lib.portfolio_value_basis import (
    LIVE_MARK_BASIS,
    STORE_BASIS,
    publish_store_totals,
    row_store_value,
    store_totals,
)


def holding(symbol: str, shares: float, live_price: float, broker_value: float, *,
            account: str = "schwab_taxable", is_cash: bool = False, **kw) -> dict:
    """One holdings row as ``portfolio_for`` leaves it: live mark, and the store's own value."""
    return {
        "account": account, "account_id": account, "symbol": symbol,
        "shares": shares, "quantity": shares,
        "price": live_price, "current_price": live_price,
        "market_value": round(shares * live_price, 2),
        "broker_shares": shares, "broker_market_value": broker_value,
        "is_cash": is_cash, **kw,
    }


ROWS = [
    holding("SCHD", 400, 100.0, 39_960.0),
    holding("SPCX", 100, 826.62, 82_700.0),
    # The 19:03 defect in miniature: 1,000 shares the broker carries at $0.30 in total, re-marked at
    # $0.2954 *per share* by a frozen backup quote. The live sum carries $295.40 the custodian does
    # not; 295.10 of the ticket's $336.88 was exactly this one row.
    holding("SRNE", 1_000, 0.2954, 0.30),
    holding("CASH", 5_000, 1.0, 5_000.0, is_cash=True),
]

STORE_TOTAL = round(sum(row_store_value(r) for r in ROWS), 2)
LIVE_TOTAL = round(sum(r["market_value"] for r in ROWS), 2)
SRNE_DRIFT = round(ROWS[2]["market_value"] - ROWS[2]["broker_market_value"], 2)  # +295.10

ACCOUNTS = [
    {"account_id": "schwab_taxable", "account_label": "Schwab Taxable", "total_usd": LIVE_TOTAL},
]


def portfolio() -> dict:
    return {
        "holdings": [dict(r) for r in ROWS],
        "accounts": [dict(a) for a in ACCOUNTS],
        "total_usd": ACCOUNTS[0]["total_usd"],
    }


def payload() -> dict:
    """The shape ``cio_truth.overview_payload`` leaves: every total is the live re-mark."""
    live = ACCOUNTS[0]["total_usd"]
    return {
        "portfolio_value": live,
        "derived_total_value": live,
        "pricing": {"canonical_total_value": live, "derived_total_value": live},
        "today_by_account": {"schwab_taxable": {"value": live, "change": 12.0}},
        "portfolio_aggregate": {
            "aggregate_value": live,
            "accounts": [{"account": "schwab_taxable", "total_value": live, "display_value": live}],
        },
        "portfolio_total": {
            "value": live,
            "basis": "row_sum",
            "basis_label": "sum of the holdings rows shown",
            "as_of": "2026-11-09T19:00:07-05:00",
            "alternatives": [{"name": "broker_marks", "value": 128_000.0}],
        },
    }


def test_the_totals_are_the_store_basis_and_the_re_mark_is_published_beside_them():
    out = publish_store_totals(payload(), portfolio())

    assert out["portfolio_value"] == STORE_TOTAL == 127_660.30
    assert out["derived_total_value"] == STORE_TOTAL
    assert out["pricing"]["canonical_total_value"] == STORE_TOTAL
    assert out["pricing"]["live_mark_total_value"] == LIVE_TOTAL

    basis = out["totals_basis"]
    assert basis["basis"] == STORE_BASIS
    assert basis["store_total"] == STORE_TOTAL
    assert basis["live_mark_total"] == LIVE_TOTAL
    assert basis["store_minus_live_mark_usd"] == round(STORE_TOTAL - LIVE_TOTAL, 2)
    assert basis["source"] == "positions_current"


def test_a_mis_scaled_quote_moves_only_the_live_mark_not_the_total():
    out = publish_store_totals(payload(), portfolio())

    # The published total is the custodian's; the 1000x mis-scaled mark moves only the re-mark beside
    # it, and the drift is named there — never hidden, and never subtracted from the store total.
    assert out["portfolio_value"] == STORE_TOTAL
    assert SRNE_DRIFT == 295.10
    assert round(LIVE_TOTAL - STORE_TOTAL, 2) == 297.10
    assert out["totals_basis"]["store_minus_live_mark_usd"] == -297.10
    live = [a for a in out["portfolio_total"]["alternatives"] if a["name"] == "live_mark_total"]
    assert live and live[0]["value"] == out["totals_basis"]["live_mark_total"]


def test_a_cash_row_is_valued_at_its_dollar_balance_not_its_share_count_times_a_price():
    cash = holding("CASH", 5_000, 1.0, 5_000.0, is_cash=True)
    assert row_store_value(cash) == 5_000.0
    # A money-market row marked at a price other than 1 never changes the dollars on the store basis.
    odd = holding("CASH", 5_000, 1.0, 5_000.0, is_cash=True, price=1.5, market_value=7_500.0)
    assert row_store_value(odd) == 5_000.0


def test_account_rows_follow_the_store_and_keep_the_re_mark_as_a_named_reading():
    out = publish_store_totals(payload(), portfolio())

    row = out["portfolio_aggregate"]["accounts"][0]
    assert row["total_value"] == STORE_TOTAL
    assert row["display_value"] == row["total_value"]
    assert row["live_total_value"] == out["totals_basis"]["live_mark_total"]

    today = out["today_by_account"]["schwab_taxable"]
    assert today["value"] == row["total_value"]
    assert today["live_value"] == row["live_total_value"]


def test_the_total_contract_is_rebuilt_on_the_store_basis():
    out = publish_store_totals(payload(), portfolio())
    contract = out["portfolio_total"]

    assert contract["value"] == out["portfolio_value"] == STORE_TOTAL
    assert contract["basis"] == STORE_BASIS
    assert contract["by_account_sum"] == contract["value"]
    assert contract["by_account"]["schwab_taxable"]["value"] == contract["value"]
    live = [a for a in contract["alternatives"] if a["name"] == "live_mark_total"]
    assert live and live[0]["value"] == out["totals_basis"]["live_mark_total"]
    assert live[0]["basis"] == LIVE_MARK_BASIS
    assert live[0]["delta"] == round(contract["value"] - live[0]["value"], 2)


def test_a_document_without_broker_values_keeps_the_re_mark_and_says_which_basis_it_is():
    bare = {"holdings": [{"account": "schwab_taxable", "symbol": "SCHD", "shares": 1,
                          "market_value": 100.0}], "accounts": [{"account_id": "schwab_taxable",
                                                                 "total_usd": 100.0}],
            "total_usd": 100.0}
    out = publish_store_totals(payload(), bare)

    assert out["portfolio_value"] == ACCOUNTS[0]["total_usd"]  # untouched: the live re-mark
    assert out["totals_basis"]["basis"] == LIVE_MARK_BASIS
    assert out["totals_basis"]["store_total"] is None
    assert "no broker value" in out["totals_basis"]["reason"]
    assert out["totals_basis"]["unvalued_rows"] == [{"account": "schwab_taxable", "symbol": "SCHD"}]


def test_one_unvalued_row_withholds_the_total_instead_of_publishing_a_short_sum():
    rows = [holding("SCHD", 400, 100.0, 39_960.0),
            {"account": "schwab_taxable", "symbol": "SPCX", "shares": 100, "market_value": 82_662.0}]
    st = store_totals({"holdings": rows})

    assert st["total"] is None
    assert st["unvalued"] == [{"account": "schwab_taxable", "symbol": "SPCX"}]
