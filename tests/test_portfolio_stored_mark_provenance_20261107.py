"""A stored mark's own provenance decides whether it may value a holding (LQ-20261107-06 follow-up).

The stored rung of `resolve_mark` is the last one, so whatever it accepts becomes the number a page
shows. Three shapes it used to accept are not prices, each refused already on the live rungs:

* a canonical mark whose source names a provider that may not price a holding (`yfinance` — the
  operator's rule — or `finviz_quote_cache`, the cache naming itself, which is the provenance loop
  LQ-20261107-03 closed for the live cache);
* a canonical mark the repricer wrote as a PROXY (`canonical_mark_type: "proxy"` /
  `not_for_valuation`): a public ticker standing in for a Fidelity fund, which the repricer itself
  refuses to value — so the reader must not value it either, and the answer is UNKNOWN, not zero;
* a legacy `price` timed by `updated_at`, which is the ROW's write time (the repricer touches every
  row each pass). Timing a price by it makes an hours-old quote look fresh forever.

Synthetic rows only; no network, no state store, no Finviz read (finviz=None is the caller's
"no live price" and keeps every case on the stored rung).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.portfolio_positions import (  # noqa: E402
    mark_source_usable,
    not_for_valuation,
    resolve_mark,
    value_and_pl,
)

NOW = dt.datetime(2026, 11, 7, 6, 15, tzinfo=dt.timezone.utc)
ROW_WRITE = "2026-11-07T06:03:05+00:00"   # the repricer's pass: every row carries it, fresh by definition


def _mark(row: dict) -> dict:
    return resolve_mark(row, finviz=None, now=NOW)


def test_a_yfinance_canonical_mark_may_not_price_a_holding():
    row = {"symbol": "XXXX", "shares": 10.0, "price": 12.5, "canonical_mark": 40.0,
           "canonical_mark_source": "yfinance",
           "canonical_mark_ingested_at": "2026-11-07T06:00:00+00:00", "updated_at": ROW_WRITE}
    mark = _mark(row)
    assert mark["price"] == 12.5, "a yfinance mark is not a price; the broker-derived price serves instead"
    assert mark["source"] == "stored_mark"
    assert mark["stale"] is True and mark["as_of"] is None, (
        "a legacy price has no quote time, so it is stale-by-unknown, not fresh-by-row-write"
    )
    assert value_and_pl(row, mark)["market_value"] == 125.0


def test_a_cache_self_labelled_mark_may_not_price_a_holding():
    """`finviz_quote_cache` contains "finviz" but is the cache naming itself (see finviz_cache)."""
    row = {"symbol": "AMANX", "shares": 10.0, "price": 79.07, "canonical_mark": 79.07,
           "canonical_mark_source": "finviz_quote_cache",
           "canonical_mark_ingested_at": "2026-11-07T06:00:06+00:00", "updated_at": ROW_WRITE}
    mark = _mark(row)
    assert mark["price"] == 79.07
    assert mark["as_of"] is None and mark["stale"] is True
    assert mark_source_usable("finviz_quote_cache") is False
    assert mark_source_usable("finviz_elite") is True
    assert mark_source_usable(None) is True          # legacy rows predate the stamp


def test_a_repricer_mark_wins_over_a_lagging_price_and_is_timed_by_its_ingest():
    """The audit's shape: the repricer's named mark vs the position build's derived copy."""
    row = {"symbol": "SRNE", "shares": 1000.0, "price": 0.0003, "canonical_mark": 0.2954,
           "canonical_mark_source": "data_broker.market_quotes:alpaca",
           "canonical_mark_ingested_at": "2026-11-06T22:00:06+00:00", "updated_at": ROW_WRITE}
    mark = _mark(row)
    assert mark["price"] == 0.2954
    assert mark["as_of"] == "2026-11-06T22:00:06+00:00", "the mark is dated by when it was ingested, not by the row write"
    assert mark["stale"] is True and mark["age_s"] > 8 * 3600
    assert value_and_pl(row, mark)["market_value"] == 295.4, "value = shares x the storable mark"


def test_a_fresh_repricer_mark_is_not_stale():
    row = {"symbol": "SPCX", "shares": 10.0, "price": 135.63, "canonical_mark": 134.27,
           "canonical_mark_source": "finviz_elite",
           "canonical_mark_ingested_at": "2026-11-07T06:00:00+00:00", "updated_at": ROW_WRITE}
    mark = _mark(row)
    assert mark["price"] == 134.27 and mark["stale"] is False and mark["age_s"] == 900


def test_a_legacy_price_is_timed_only_by_its_own_quote_field():
    """`updated_at` is the row's write time; a price it alone dates is unknown, never fresh."""
    row = {"symbol": "NVDA", "shares": 10.0, "price": 186.64, "updated_at": ROW_WRITE}
    mark = _mark(row)
    assert mark["price"] == 186.64 and mark["as_of"] is None and mark["stale"] is True

    timed = dict(row, price_bar_end="2026-11-07T06:10:00+00:00")
    mark = _mark(timed)
    assert mark["as_of"] == "2026-11-07T06:10:00+00:00" and mark["stale"] is False and mark["age_s"] == 300


def test_a_proxy_mark_never_values_the_holding():
    row = {"symbol": "FID-DIVINTL", "shares": 100.0, "price": 10.0, "canonical_mark": 55.0,
           "canonical_mark_type": "proxy", "not_for_valuation": True,
           "canonical_mark_source": "proxy_public_ticker", "canonical_mark_as_of": "2026-11-06",
           "updated_at": ROW_WRITE}
    assert not_for_valuation(row) is True
    mark = _mark(row)
    assert mark["price"] is None and mark["source"] == "none" and mark["stale"] is True
    assert value_and_pl(row, mark)["market_value"] is None, "unknown is not zero and not a proxy multiple"
    # The row-level flag alone is enough, without the mark type.
    assert not_for_valuation({"not_for_valuation": "true"}) is True
    assert not_for_valuation({"canonical_mark_type": "nav_proxy"}) is True
    assert not_for_valuation({"canonical_mark_type": "unknown"}) is False


def test_a_live_price_still_wins_over_a_stored_proxy():
    """The exclusion is about the STORED rung: a real live quote for the instrument is still evidence."""
    row = {"symbol": "FID-DIVINTL", "shares": 100.0, "canonical_mark_type": "proxy",
           "not_for_valuation": True, "canonical_mark": 55.0}
    mark = resolve_mark(row, finviz={"price": 61.25, "as_of": "2026-11-07T06:14:00+00:00"}, now=NOW)
    assert mark["price"] == 61.25 and mark["source"] == "finviz"

def test_zero_is_never_a_candidate():
    row = {"symbol": "628518102", "shares": 1.0, "price": 0.0, "canonical_mark": 0.0,
           "canonical_mark_source": "schwab", "updated_at": ROW_WRITE}
    mark = _mark(row)
    assert mark["price"] is None and mark["source"] == "none"
    assert value_and_pl(row, mark)["market_value"] is None
