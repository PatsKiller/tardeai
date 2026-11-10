"""ROTATION_WHOLE_SHARE_1654_20261109 — LQ-20261107-1654 (P0, operator-requested): the Home rotation card sizes in
WHOLE SHARES at the CURRENT quote.

Before this ticket the card printed a share count off the last DAILY CLOSE (market_ohlcv_bars), so the number the
operator read was priced at yesterday's close. Now every tranche (30/30/40) and every candidate is
``floor(tranche_usd / live price)`` shares plus the cash that does not buy another share, the price comes from the
intraday quote tier only (Finviz <=30 min, else a fresh broker row — api_v2._fresh_price_batch, which drops
yfinance), the card states "Prices as of <ET time>" from the OLDEST quote in the batch, and a missing or unstampable
quote yields NO share count rather than a count at a stale price.

The operator's worked example: $15,065 at 184.80 -> 81 shares, $96.20 left over. (The ticket wrote "$95.20"; that is
the leftover of a $15,064.00 tranche — 81 x 184.80 = 14,968.80 — so the arithmetic below follows floor + remainder.)

Synthetic fixtures only (public repo): the DEMO-family records of tests/test_home_cio_card_20261108.
AUTHORITY: READ_ONLY_ADVISORY. Nothing here sizes an order; the proposal is labelled ``proposed: true``.
"""
from __future__ import annotations

import copy
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from lib import home_cio_card as h  # noqa: E402
from test_home_cio_card_20261108 import MR, SC, _build, buys_open  # noqa: E402  (synthetic fixture, one source)

PRICE = 184.80
AS_OF = "2031-03-10T14:45:00+00:00"
Q_XLV = {"price": PRICE, "as_of": AS_OF, "source": "finviz_quote_cache"}
Q_XLP = {"price": 85.40, "as_of": "2031-03-10T15:10:00+00:00", "source": "finviz_quote_cache"}


def _rot(**kw):
    # LQ-20261107-1389: this file is about the whole-share SIZING rule, and the shared fixture's buys verdict
    # withholds a tranche (which is the point of 1389). It is read here under a buys line that allows one; the
    # withholding has its own tests in test_home_cio_cio_verdict_lq1389_20261109.py. `buys_open` carries the
    # `until`, so this file keeps reading the catalyst label too (LQ-20261107-1735).
    sc = buys_open(kw.pop("sc", SC))
    kw.setdefault("quotes", {"XLV": copy.deepcopy(Q_XLV), "XLP": copy.deepcopy(Q_XLP)})
    return _build(sc=sc, **kw)["panel"]["rotate"]


def _by(rot):
    return {c["symbol"]: c for c in rot["candidates"]}


# ── the arithmetic ───────────────────────────────────────────────────────────────────────────────────────────────

def test_whole_share_arithmetic_matches_the_operator_example():
    # floor(15,065 / 184.80) = floor(81.52) = 81; cash left = 15,065 - 81 x 184.80 = 96.20.
    assert h.shares_for(15065.0, PRICE) == (81, 96.20)
    # The ticket's "$95.20" belongs to a $15,064.00 tranche, the same 81 shares: 15,064 - 14,968.80 = 95.20.
    assert h.shares_for(15064.0, PRICE) == (81, 95.20)


def test_an_exact_multiple_keeps_every_share():
    # 1000 / 25.0 must be 40 shares and $0 left, not 39 and $25 (binary float floors down without the epsilon).
    assert h.shares_for(1000.0, 25.0) == (40, 0.0)
    # A tranche smaller than one share buys none and leaves all of it in cash.
    assert h.shares_for(500.0, 1000.0) == (0, 500.0)


@pytest.mark.parametrize("usd,price", [(None, PRICE), (0.0, PRICE), (15065.0, None), (15065.0, 0.0), (15065.0, -3.0),
                                       (float("nan"), PRICE)])
def test_no_price_and_no_dollars_are_no_count(usd, price):
    assert h.shares_for(usd, price) == (None, None)


def test_every_tranche_is_sized_in_whole_shares_at_the_live_price():
    rows = h.tranche_rows(15065.0, PRICE)
    assert [r["tranche"] for r in rows] == [1, 2, 3]
    assert [r["usd"] for r in rows] == [4520.0, 4520.0, 6026.0]  # the operator's 30/30/40 split of $15,065
    assert [r["shares"] for r in rows] == [24, 24, 32]
    for r in rows:
        assert r["leftover_usd"] == round(r["usd"] - r["shares"] * PRICE, 2)
        assert 0 <= r["leftover_usd"] < PRICE


def test_no_price_sizes_no_tranche():
    rows = h.tranche_rows(15065.0, None)
    assert [(r["shares"], r["leftover_usd"]) for r in rows] == [(None, None)] * 3
    assert [r["usd"] for r in rows] == [4520.0, 4520.0, 6026.0]  # the dollars are still the target; only sizing stops


# ── the card ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_live_quote_sizes_the_card_and_states_its_time():
    rot = _rot()
    by = _by(rot)
    assert by["XLV"]["price"] == {"value": PRICE, "source_id": "quote:finviz_quote_cache", "as_of": AS_OF}
    # XLV: 4% of a $100,000 book = $4,000; tranche 1 = 30% = $1,200; floor(1200 / 184.80) = 6 shares.
    assert by["XLV"]["proposed"]["tranche1_usd"] == 1200.0 and by["XLV"]["proposed"]["shares"] == 6
    assert by["XLV"]["proposed"]["priced"] is True
    assert by["XLV"]["proposed"]["tranches"] == [
        {"tranche": 1, "usd": 1200.0, "shares": 6, "leftover_usd": 91.2},
        {"tranche": 2, "usd": 1200.0, "shares": 6, "leftover_usd": 91.2},
        {"tranche": 3, "usd": 1600.0, "shares": 8, "leftover_usd": 121.6},
    ]
    # XLP: 3% = $3,000; tranche 1 = $900; floor(900 / 85.40) = 10 shares and $46.00 left.
    assert by["XLP"]["proposed"]["tranches"][0] == {"tranche": 1, "usd": 900.0, "shares": 10, "leftover_usd": 46.0}
    # The card states the quote time it sized at: the OLDEST quote in the batch, so it holds for every row.
    assert rot["prices_as_of"] == AS_OF
    assert rot["prices_sources"] == ["quote:finviz_quote_cache"]
    assert not rot.get("prices_missing")


def test_the_prior_daily_close_is_never_a_sizing_price():
    # The defect this ticket closes: bars are present and the close is a number, but no quote -> no share count.
    rot = _rot(quotes={})
    by = _by(rot)
    xlv = by["XLV"]
    assert xlv["close"]["value"] > 0  # the close is still shown as CONTEXT
    assert "price" not in xlv
    assert xlv["proposed"]["shares"] is None and xlv["proposed"]["priced"] is False
    assert all(t["shares"] is None and t["leftover_usd"] is None for t in xlv["proposed"]["tranches"])
    assert rot.get("prices_as_of") is None  # item() drops a None: absent means "no quote at all"
    assert rot["prices_missing"] == ["XLV", "XLP"]  # the qualifying groups the card could not price


@pytest.mark.parametrize("bad", [
    None,                                                              # no quote at all
    {"price": None, "as_of": AS_OF, "source": "finviz_quote_cache"},   # a row with no number
    {"price": 0.0, "as_of": AS_OF, "source": "finviz_quote_cache"},    # a zero quote is a data error
    {"price": -184.8, "as_of": AS_OF, "source": "finviz_quote_cache"},
    {"price": PRICE, "as_of": None, "source": "finviz_quote_cache"},   # no time -> cannot be shown as "as of"
    {"price": PRICE, "as_of": "2031-03-10 14:45:00 ET", "source": "x"},  # unnormalised Finviz stamp
    {"price": PRICE, "as_of": "2031-03-10T14:45:00", "source": "x"},     # naive: no instant
    {"price": PRICE, "as_of": "yesterday", "source": "x"},
    {"price": PRICE, "as_of": AS_OF},                                  # no source: provenance is not optional
])
def test_an_unusable_quote_fails_closed(bad):
    rot = _rot(quotes={"XLV": copy.deepcopy(bad) if bad is not None else None,
                       "XLP": copy.deepcopy(Q_XLP)})
    by = _by(rot)
    assert "price" not in by["XLV"]
    assert by["XLV"]["proposed"]["shares"] is None and by["XLV"]["proposed"]["priced"] is False
    assert all(t["shares"] is None for t in by["XLV"]["proposed"]["tranches"])
    assert "XLV" in (rot["prices_missing"] or [])
    # XLP is still priced, so the batch still states ITS time — and only XLV is reported as missing.
    assert rot["prices_as_of"] == Q_XLP["as_of"] and rot["prices_missing"] == ["XLV"]


def test_prices_as_of_is_the_oldest_instant_not_the_longest_string():
    # "2031-03-10T10:50:00-04:00" is 14:50Z, LATER than 14:45Z, yet it sorts first as text. The card must name the
    # instant (14:45Z), or "Prices as of" would overstate how fresh the oldest row is.
    later_offset = {"price": 85.40, "as_of": "2031-03-10T10:50:00-04:00", "source": "finviz_quote_cache"}
    rot = _rot(quotes={"XLV": copy.deepcopy(Q_XLV), "XLP": later_offset})
    assert rot["prices_as_of"] == AS_OF


def test_a_stale_document_still_proposes_nothing():
    mr = copy.deepcopy(MR)
    mr["stale"] = True
    out = _build(mr=mr)
    assert out["advice"]["ok"] is False
    assert all("proposed" not in c for c in out["panel"]["rotate"]["candidates"])


def test_the_card_never_emits_a_share_count_without_a_quote_time():
    # Every proposed share count on the wire is paired with the price fact it was computed at.
    rot = _rot()
    for c in rot["candidates"]:
        p = c.get("proposed") or {}
        if p.get("shares") is not None:
            assert c.get("price") and c["price"]["as_of"] and c["price"]["source_id"]
            assert c["price"]["value"] == (PRICE if c["symbol"] == "XLV" else Q_XLP["price"])
    # The quote time is its own fact: it is not the sector record's as_of, which says nothing about prices.
    assert datetime.fromisoformat(rot["prices_as_of"]).tzinfo is not None
    assert rot["as_of"] == MR["sectors"]["as_of"] and rot["prices_as_of"] != rot["as_of"]
