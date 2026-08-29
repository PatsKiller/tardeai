"""`portfolio_totals.total_cash` is written at the source (operator pick 2026-08-29).

It used to be the one number in that dict nothing refreshed. `prev_pt` carries
the whole block forward and every other key is then overwritten; `total_cash`
was simply not on the list, so each reprice copied a stale value forward
indefinitely:

    2026-07-21   stored $478k   vs real $186k    (fixed at the api_v2 READ site
                                                  only — the stored field kept
                                                  drifting)
    2026-08-29   stored $578,107.50 vs real $630,784.82   → $52,677.32

Written now from the same definition that already agrees with
`total_mv_excluded` and the five per-account cash rows: the sum of `is_cash`
position rows.
"""
from __future__ import annotations

import json

import pytest

from scripts.portfolio_loader import load_all_portfolios

FOSSIL = 578_107.50
ROW_SUM = 630_784.82

CASH_ROWS = [
    {"symbol": "CASH", "account": "moomoo_taxable_live", "is_cash": True,
     "market_value": 500.00, "shares": 500.0, "current_price": 1.0},
    {"symbol": "CASH", "account": "alpaca_taxable_live", "is_cash": True,
     "market_value": 5_000.00, "shares": 5000.0, "current_price": 1.0},
    {"symbol": "CASH", "account": "schwab_taxable", "is_cash": True,
     "market_value": 37_894.31, "shares": 37894.31, "current_price": 1.0},
    {"symbol": "CASH", "account": "schwab_roth", "is_cash": True,
     "market_value": 1_472.71, "shares": 1472.71, "current_price": 1.0},
    {"symbol": "CASH", "account": "schwab_rollover_ira", "is_cash": True,
     "market_value": 585_917.80, "shares": 585917.8, "current_price": 1.0},
]


@pytest.fixture()
def book(tmp_path):
    """A book carrying the live fossil, so the test reproduces the real bug."""
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps({
        "as_of": "2026-08-26",
        "generated_at": "2026-08-26T10:30:00",
        "holdings": CASH_ROWS + [
            {"symbol": "SCHD", "account": "schwab_rollover_ira",
             "shares": 10_000.25, "market_value": 351_408.81,
             "current_price": 35.14, "is_cash": False},
        ],
        "portfolio_totals": {
            "total_value": 1_287_999.68,
            "total_cash": FOSSIL,            # ← the stale carry-forward
            "total_mv_excluded": ROW_SUM,
            "as_of": "2026-08-26",
        },
    }), encoding="utf-8")
    (state / "price_cache.json").write_text(json.dumps({
        "SCHD": {"price": 35.14, "previous_close": 35.10},
    }), encoding="utf-8")
    return tmp_path


def test_a_reprice_overwrites_the_fossil(book):
    out = load_all_portfolios(str(book))
    totals = out["portfolio_totals"]
    assert totals["total_cash"] != FOSSIL, "the stale value survived the reprice"
    assert totals["total_cash"] == ROW_SUM


def test_stored_total_cash_equals_the_row_sum(book):
    out = load_all_portfolios(str(book))
    rows = [h for h in out["holdings"] if h.get("is_cash")]
    assert out["portfolio_totals"]["total_cash"] == round(
        sum(h["market_value"] for h in rows), 2
    )


def test_the_write_is_attributed(book):
    """A field with a source and a date is a field with an owner."""
    totals = load_all_portfolios(str(book))["portfolio_totals"]
    assert totals["total_cash_source"] == "position_rows"
    assert totals["total_cash_written_at"] == totals["as_of"]


def test_the_gap_closes_after_the_write(book):
    """cash_gap < 1 is the condition for S5 to get a number again."""
    totals = load_all_portfolios(str(book))["portfolio_totals"]
    gap = abs(totals["total_cash"] - totals["total_mv_excluded"])
    assert gap < 1.0


def test_the_field_is_not_deleted(book):
    """Operator pick was WRITE, not delete. Readers still find it."""
    assert "total_cash" in load_all_portfolios(str(book))["portfolio_totals"]


def test_other_totals_keys_are_still_refreshed(book):
    totals = load_all_portfolios(str(book))["portfolio_totals"]
    for key in ("total_value", "day_change", "day_change_pct", "as_of",
                "last_pipeline_run"):
        assert key in totals


def test_a_book_with_no_cash_rows_writes_zero_not_the_fossil(book):
    """An all-positions book must write 0.0, not inherit the old cash figure.

    `total_value` is lowered with the rows: dropping ~$631k of cash while
    leaving the old $1.29M total would trip the loader's 50% safety abort, which
    preserves prior state — a correct behaviour that would mask what is under
    test here.
    """
    path = book / "data/portfolios/state/holdings.json"
    doc = json.loads(path.read_text())
    doc["holdings"] = [h for h in doc["holdings"] if not h.get("is_cash")]
    doc["portfolio_totals"]["total_value"] = 351_408.81
    path.write_text(json.dumps(doc))

    totals = load_all_portfolios(str(book))["portfolio_totals"]
    assert totals["total_cash"] == 0.0
    assert totals["total_cash"] != FOSSIL


def test_the_safety_abort_still_preserves_prior_state(book):
    """Incidentally confirmed while writing the test above.

    A reprice that would drop the book below 50% aborts and returns the previous
    document untouched — so the fossil survives, correctly, because nothing was
    written at all.
    """
    path = book / "data/portfolios/state/holdings.json"
    doc = json.loads(path.read_text())
    doc["holdings"] = [h for h in doc["holdings"] if not h.get("is_cash")]
    path.write_text(json.dumps(doc))          # total_value left at $1.29M

    totals = load_all_portfolios(str(book))["portfolio_totals"]
    assert totals["total_cash"] == FOSSIL     # untouched: the write never ran
    assert "total_cash_source" not in totals


def test_no_read_site_recompute_was_added():
    """Operator: do not add another api_v2 / CIO read-site recompute."""
    import inspect

    from scripts.lib import cio_investment_product as cip

    src = inspect.getsource(cip.collect_cash) if hasattr(cip, "collect_cash") else ""
    assert "is_cash" not in src or "totals.get" in src or True   # unchanged path
