"""LQ-20261113-3124R — a re-mark is not a price move.

Synthetic fixtures only. On 2026-11-13 ``finviz_reprice`` re-marked every row at the live quote and, for each
row whose broker ``price`` sat below the mark its stored ``day_change`` had been computed at, added that whole
difference into "today". That is how the same book published two different figures under the name "1D": the
page's "today" had swallowed a **valuation correction**. The production values stay in persistent-state scratch
(FINDING-LQ-20261113-3124R) and are deliberately not repeated here; the repository is public.

The delta must be measured from the mark the day change was computed at — the writer's own
``day_change_mark_price`` stamp, else the mark alias the value came from (``canonical_mark``/``current_price``) —
and only fall back to ``price`` when the row carries no better provenance. ``price`` is the broker's
regular-session mark; the repricer never rewrites it, so it names a different clock than the day change.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
from lib import cio_truth as ct  # noqa: E402
from lib import portfolio_measures as pm  # noqa: E402

NOW = datetime(2026, 11, 13, 22, 52, tzinfo=timezone.utc)   # 17:52 ET, 2026-11-13


def _row(**kw):
    row = {"account": "fixture_taxable", "symbol": "ZZTA", "shares": 10, "price": 100.0,
           "market_value": 1000.0, "price_source": "data_broker.market_quotes:schwab"}
    row.update(kw)
    return row


def _fv(price, symbol="ZZTA"):
    return {symbol: {"price": price, "last_fetched": "2026-11-13 17:45:00 ET"}}


def _one(row, price, **kw):
    return ct.finviz_reprice({"holdings": [row]}, _fv(price), now=NOW, **kw)["holdings"][0]


def test_a_re_mark_to_the_mark_the_day_change_was_computed_at_does_not_move_today():
    """The incident, one row: the broker mark $100 and the live mark $110 differ, but the day change was written
    at $110 — so re-marking to $110 is zero move. The old baseline (``price``) invented −$100 of "today"."""
    out = _one(_row(price=100.0, canonical_mark=110.0, day_change=-10.0), 110.0)
    assert out["price"] == 110.0 and out["market_value"] == 1100.0
    assert out["day_change"] == -10.0
    assert out["day_change_mark_price"] == 110.0


def test_the_writers_own_stamp_is_the_first_baseline():
    out = _one(_row(price=100.0, canonical_mark=110.0, day_change_mark_price=109.0, day_change=5.0), 111.0)
    assert out["day_change"] == 25.0          # 5 + (111 - 109) * 10
    assert out["day_change_mark_price"] == 111.0


def test_a_real_move_after_the_stamp_still_adjusts_the_day_change():
    out = _one(_row(price=100.0, canonical_mark=110.0, day_change=5.0), 108.0)
    assert out["day_change"] == -15.0         # 5 + (108 - 110) * 10
    assert out["day_change_mark_price"] == 108.0


def test_a_row_with_no_provenance_keeps_the_price_baseline():
    """No stamp and no mark alias: ``price`` is the only clock the row declares, so it is the baseline (the
    pre-existing behaviour the 2026-11-07 suite pins)."""
    out = _one(_row(price=20.0, market_value=200.0, day_change=5.0), 18.0)
    assert out["day_change"] == -15.0         # 5 + (18 - 20) * 10
    assert out["day_change_mark_price"] == 18.0


def test_the_stamp_is_advanced_so_a_second_re_mark_measures_from_the_first():
    doc = {"holdings": [_row(price=100.0, canonical_mark=110.0, day_change=-10.0)]}
    once = ct.finviz_reprice(doc, _fv(110.0), now=NOW)
    twice = ct.finviz_reprice(once, _fv(112.0), now=NOW)["holdings"][0]
    assert twice["day_change"] == -10.0 + 2.0 * 10.0     # measured from 110, not from the broker's 100
    assert twice["day_change_mark_price"] == 112.0


def test_a_row_without_a_day_change_gains_no_invented_one():
    out = _one(_row(price=100.0, canonical_mark=110.0, day_change=None), 112.0)
    assert out["price"] == 112.0
    assert out["day_change"] is None
    assert "day_change_mark_price" not in out


def test_cash_is_never_re_marked():
    cash = {"account": "fixture_taxable", "symbol": "CASH", "is_cash": True, "shares": 500, "price": 1.0,
            "market_value": 500.0, "day_change": 0.0}
    out = ct.finviz_reprice({"holdings": [cash]}, {"CASH": {"price": 2.0,
                                                           "last_fetched": "2026-11-13 17:45:00 ET"}},
                            now=NOW)["holdings"][0]
    assert out["market_value"] == 500.0 and out["day_change"] == 0.0


def test_the_re_mark_is_a_finviz_estimate_beside_the_broker_anchor_never_inside_it():
    """End to end on one book: the broker mark is $100 and the live mark $110, while the day change was written at
    the live mark. The broker-anchored price move is the broker pair ($100 against its $101.10 prior close); the
    re-mark's $100 lives only in the separate Finviz estimate. Summing the two would be the 2026-11-13 defect."""
    store = {"holdings": [_row(price=100.0, canonical_mark=110.0, day_change=-10.0, market_value=1100.0,
                               broker_market_value=1000.0, prior_close=101.10)]}
    live = ct.finviz_reprice(store, _fv(110.0), now=NOW)
    assert live["holdings"][0]["day_change"] == -10.0
    m = pm.portfolio_measures(live, now=NOW)["measures"]
    assert m["price_move_estimate"]["value"] == -11.0            # 10 x (100.00 - 101.10), broker marks
    assert m["price_move_estimate"]["rows"][0]["baseline_source"] == "broker_prior_close"
    assert m["account_value"]["value"] == 1000.0                 # the broker anchor
    assert m["account_value"]["finviz_estimate"]["value"] == 1100.0
    assert m["account_value"]["finviz_estimate"]["delta"] == 100.0
    assert m["price_move_estimate"]["finviz_estimate"]["total_with_broker_nav"] == -10.0
    assert "never added" in m["price_move_estimate"]["finviz_estimate"]["note"]
