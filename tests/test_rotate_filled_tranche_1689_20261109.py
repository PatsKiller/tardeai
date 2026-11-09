"""ROTATE_FILLED_TRANCHE_1689_20261109 — LQ-20261107-1689 (P1): the Home Rotate card must know what the book
already holds.

The operator bought the XLV tranche-1 shares in a Schwab account at ~15:40 ET on 2026-11-09. The position landed in
``positions_current`` (79 sh, avg 188.42, as_of 15:54), and the Home "Rotate · defensives" card still offered Tranche 1
as "PROPOSED · NEEDS YOUR OK" and printed "Cash after tranche 1 73.3%" — a number that had ALREADY been spent, then
subtracted again. A proposal the book has already executed is not a proposal; it is a fill.

Rule (operator 2026-11-09): the rotation plan reads the held quantity per ETF, and a holding of at least ~90% of the
planned tranche-1 shares marks that tranche FILLED (with the shares, average cost and date actually held). Cash after
tranche 1 counts the money still to be spent: a filled tranche is not deducted a second time. The next step is then
Tranche 2, after the configured catalyst (the CIO's "no new buys until ..." label, e.g. "CPI Tue 11-10 08:30 ET").

Synthetic fixtures only (public repo): the DEMO-family records of tests/test_home_cio_card_20261108, with round
dollar figures. The replay below mirrors the SHAPE of the 2026-11-09 case (a tranche already bought), never the
operator's real quantities or prices.
AUTHORITY: READ_ONLY_ADVISORY. Nothing here sizes an order; a filled tranche is a fact about the book, not a command.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from lib import home_cio_card as h  # noqa: E402
from test_home_cio_card_20261108 import MR, SC, _build  # noqa: E402  (synthetic fixture, one source)

PRICE = 184.80            # XLV quote
PRICE_XLP = 85.40         # XLP quote
QUOTE_AT = "2031-03-10T14:45:00+00:00"
HOLD_AT = "2031-03-10T19:54:02+00:00"   # the holding store row's as_of
BOOK = 1_000_000.0
CASH = 750_000.0

QUOTES = {"XLV": {"price": PRICE, "as_of": QUOTE_AT, "source": "finviz_quote_cache"},
          "XLP": {"price": PRICE_XLP, "as_of": QUOTE_AT, "source": "finviz_quote_cache"}}


def _book(mr, total=BOOK, cash=CASH):
    """The DEMO record rescaled to a round synthetic book, so the tranche sizes are readable."""
    mr = copy.deepcopy(mr)
    mr["book_exposure"]["total_usd"] = total
    mr["book_exposure"]["cash_usd"] = cash
    mr["book_exposure"]["cash_pct_book"] = round(cash / total * 100, 1)
    return mr


def _hold(symbol, shares, avg, *, as_of=HOLD_AT, run=918, account="example_ira", cash=False):
    """One holdings-store row, shaped like the store the API joins: shares/quantity, basis, as_of, sync_run_id."""
    return {"symbol": symbol, "account": account, "shares": shares, "quantity": shares,
            "cost_basis_total": round(shares * avg, 2), "is_cash": cash, "as_of": as_of, "sync_run_id": run}


def _rot(*, holdings=None, quotes=None, mr=None):
    kw = {"holdings": holdings}
    kw["quotes"] = dict(QUOTES if quotes is None else quotes)
    return _build(mr=_book(mr or MR), **kw)["panel"]["rotate"]


def _by(rot):
    return {c["symbol"]: c for c in rot["candidates"]}


# XLV is LEADERSHIP_CONFIRMED -> 4% of a $1,000,000 book = $40,000; tranche 1 (30%) = $12,000 -> 64 shares at 184.80.
# XLP is RESILIENT -> 3% = $30,000; tranche 1 = $9,000 -> 105 shares at 85.40.
XLV_T1_SHARES = 64
XLP_T1_SHARES = 105


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_holding_of_at_least_ninety_percent_of_the_tranche_is_filled():
    assert h.tranche1_filled(64, XLV_T1_SHARES) is True      # exactly the tranche
    assert h.tranche1_filled(63, XLV_T1_SHARES) is True      # 98.4% — a share short is still the tranche
    assert h.tranche1_filled(58, XLV_T1_SHARES) is True      # 90.6%, the first count over the line
    assert h.tranche1_filled(57, XLV_T1_SHARES) is False     # 89.1%, under the line


@pytest.mark.parametrize("held,tranche", [(None, 64), (63, None), (0, 64), (63, 0), (-5, 64), (float("nan"), 64)])
def test_no_fill_can_be_claimed_without_both_real_numbers(held, tranche):
    # An unknown holding is not a fill, and a tranche that could not be sized (no live quote) can never be "filled".
    assert h.tranche1_filled(held, tranche) is False


# ── the card ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_tranche_bought_in_the_book_is_not_offered_again():
    rot = _rot(holdings=[_hold("XLV", 63, 181.0)])
    xlv = _by(rot)["XLV"]
    held = xlv["held"]
    assert held["shares"] == 63 and held["filled"] is True
    assert held["avg_cost"] == 181.0
    assert held["pct_of_tranche1"] == 98.4
    # The fact names the table it came from and the run and instant it was captured at — never a bare number.
    assert held["source_id"] == "positions_current:sync_run_918"
    assert held["as_of"] == HOLD_AT


def test_a_symbol_the_book_does_not_hold_shows_no_held_record():
    rot = _rot(holdings=[])
    assert all("held" not in c for c in rot["candidates"])
    assert rot["plan"]["tranche1_filled"] is False
    assert rot["plan"]["cash_after_pct"] == round((CASH - 21_000.0) / BOOK * 100, 1)  # 72.9: both tranches to buy


def test_the_cash_line_does_not_spend_a_filled_tranche_twice():
    # Both tranches are in the book: nothing is left to buy, so cash after tranche 1 IS the cash the book holds.
    rot = _rot(holdings=[_hold("XLV", 64, 181.0), _hold("XLP", 105, 85.0, account="example_taxable")])
    assert rot["plan"]["tranche1_filled"] is True
    assert rot["plan"]["cash_after_pct"] == 75.0
    # The proposal itself is still stated (what the tranche was): the card reports a fill, it does not erase the plan.
    assert rot["plan"]["tranche1_usd"] == 21_000.0


def test_an_unfilled_tranche_is_still_deducted():
    # XLV bought, XLP not: only XLP's $9,000 is still to be spent.
    rot = _rot(holdings=[_hold("XLV", 64, 181.0)])
    assert _by(rot)["XLV"]["held"]["filled"] is True
    assert "held" not in _by(rot)["XLP"]
    assert rot["plan"]["tranche1_filled"] is False
    assert rot["plan"]["cash_after_pct"] == round((CASH - 9_000.0) / BOOK * 100, 1)  # 74.1


def test_the_next_step_is_tranche_2_after_the_configured_catalyst():
    rot = _rot(holdings=[_hold("XLV", 64, 181.0), _hold("XLP", 105, 85.0)])
    # The catalyst label is the CIO's own "no new buys until ..." gate, never a date this card invents.
    assert rot["plan"]["tranche2_after"] == "CPI Tue 03-11 08:30 ET"


def test_a_position_without_a_live_price_is_never_called_filled():
    rot = _rot(holdings=[_hold("XLV", 64, 181.0)], quotes={})
    xlv = _by(rot)["XLV"]
    assert xlv["held"]["shares"] == 64            # the holding is a fact and is still shown
    assert xlv["held"]["filled"] is False         # but with no price there is no tranche size to compare against
    assert "pct_of_tranche1" not in xlv["held"]   # item() drops the None: no invented percentage


def test_holdings_are_summed_across_accounts_and_cash_is_not_a_holding():
    rot = _rot(holdings=[_hold("XLV", 30, 180.0),
                         _hold("XLV", 34, 182.0, account="example_taxable"),
                         _hold("CASH", 900_000.0, 1.0, cash=True)])
    held = _by(rot)["XLV"]["held"]
    assert held["shares"] == 64 and held["filled"] is True
    # (30 x 180 + 34 x 182) / 64 = 181.0625 -> 181.06
    assert held["avg_cost"] == 181.06
    assert "CASH" not in {c["symbol"] for c in rot["candidates"]}


def test_cash_is_recognised_by_the_shared_predicate_not_a_local_flag():
    # LQ-1688/1689 must agree on what cash is: a sweep row that carries only the symbol (no is_cash flag, no CASH
    # class) is still cash. lib.holdings_universe.is_cash_row decides; the card keeps no list of its own.
    rows = [{"symbol": "cash", "shares": 900_000.0, "avg_cost": 1.0, "cost_basis_total": 900_000.0,
             "as_of": HOLD_AT, "sync_run_id": 918},
            _hold("XLV", 64, 181.0)]
    held = h._held_by_symbol(rows)
    assert set(held) == {"XLV"} and held["XLV"]["shares"] == 64


def test_a_held_row_without_a_capture_time_is_dropped():
    # positions_current rows always carry as_of; a row that cannot be dated cannot be shown as a fact.
    rot = _rot(holdings=[{"symbol": "XLV", "shares": 64, "avg_cost": 181.0, "sync_run_id": 918}])
    assert "held" not in _by(rot)["XLV"]


def test_a_stale_record_claims_no_fill():
    mr = copy.deepcopy(MR)
    mr["stale"] = True
    out = _build(mr=mr, holdings=[_hold("XLV", 64, 181.0)], quotes=dict(QUOTES))
    rot = out["panel"]["rotate"]
    assert out["advice"]["ok"] is False
    assert all("held" not in c and "proposed" not in c for c in rot["candidates"])
    assert "plan" not in rot


def test_a_group_that_does_not_qualify_offers_no_tranche_to_fill():
    # XLU is NEUTRAL: it shows a target (2% of book) and "starts when it turns RESILIENT" — never a tranche, so a
    # position in it can neither fill one nor be reported as a fill.
    rot = _rot(holdings=[_hold("XLU", 500, 41.0)])
    xlu = _by(rot)["XLU"]
    assert xlu["qualifies"] is False
    assert xlu["proposed"]["tranche1_usd"] is None
    assert "held" not in xlu


# ── the replay ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_live_shape_of_the_20261109_buy_is_a_fill():
    """79 shares held against an 80-share tranche 1 (98.75%) is a fill; a share count a fifth short is not.

    The numbers are the live ones only in RATIO — 79 of 80 was the 2026-11-09 position against its plan. The card
    never sees an absolute quantity from the operator's book here: the rule is a ratio, and this pins its edge.
    """
    assert h.tranche1_filled(79, 80) is True
    assert h.tranche1_filled(71, 80) is False    # 88.75%: nine shares short of the plan is not a rounding
    assert h.tranche1_filled(72, 80) is True     # exactly 90%


def test_replay_of_the_20261109_fill():
    """The operator's 2026-11-09 sequence, in synthetic numbers: tranche 1 bought, card must say so.

    Before this ticket the card printed the whole proposal a second time and a cash line that subtracted the money
    already spent. After it: the tranche reads FILLED with the shares/avg/date actually held, cash after tranche 1 is
    the book's real cash, and the next step is Tranche 2 after the CPI gate.
    """
    rot = _rot(holdings=[_hold("XLV", XLV_T1_SHARES, 181.0)])
    xlv = _by(rot)["XLV"]

    assert xlv["proposed"]["tranche1_usd"] == 12_000.0      # the plan that was executed
    assert xlv["held"]["shares"] == XLV_T1_SHARES
    assert xlv["held"]["filled"] is True
    assert rot["plan"]["tranche1_filled"] is False          # XLP's tranche 1 is still unbought
    assert rot["plan"]["cash_after_pct"] == round((CASH - 9_000.0) / BOOK * 100, 1)
    assert rot["plan"]["tranche2_after"] == "CPI Tue 03-11 08:30 ET"

    # And with the second tranche bought too, the panel offers nothing left in tranche 1.
    rot2 = _rot(holdings=[_hold("XLV", XLV_T1_SHARES, 181.0), _hold("XLP", XLP_T1_SHARES, 85.0)])
    assert rot2["plan"]["tranche1_filled"] is True
    assert rot2["plan"]["cash_after_pct"] == 75.0
