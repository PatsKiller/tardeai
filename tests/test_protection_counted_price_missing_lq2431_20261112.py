"""LQ-20261107-2431 (FINDING F1 from LQ-2412): a holding with no market value stays counted.

Before: cio_truth.protection_for computed ``counted = kind is None and (value or 0) >= COUNT_FLOOR_USD``. A missing
price became $0, so an unpriced GAP fell below the $100 floor and dropped out of every protection rollup
(stops_protection, the headline). Unknown is never small: only a KNOWN value under the floor is not counted.
Synthetic fixtures only.
"""
from datetime import datetime, timezone

import pytest

from scripts.lib import cio_truth as truth
from scripts.lib import stops_protection as sp

NOW = datetime(2026, 11, 12, 16, 0, tzinfo=timezone.utc)
SCHWAB = "schwab_synth_taxable"


def pos(**over):
    p = {"symbol": "SYNP", "account_id": SCHWAB, "shares": 10, "market_value": None, "stop_state": None,
         "stop_source": None, "stop_price": None, "stop_captured_at": NOW.isoformat()}
    p.update(over)
    return p


@pytest.mark.parametrize("missing", [None, "", "n/a"])
def test_unpriced_gap_stays_counted_and_is_flagged(missing):
    out = truth.protection_for(pos(market_value=missing), broker_available=True)
    assert out["protection_state"] == "GAP"
    assert out["protection"]["counted"] is True
    assert out["protection"]["price_missing"] is True


def test_known_value_under_floor_is_still_not_counted():
    out = truth.protection_for(pos(market_value=40.0), broker_available=True)
    assert out["protection"]["counted"] is False and out["protection"]["price_missing"] is False


def test_zero_value_is_a_known_value_not_a_missing_one():
    out = truth.protection_for(pos(market_value=0), broker_available=True)
    assert out["protection"]["counted"] is False and out["protection"]["price_missing"] is False


def test_at_floor_and_above_counted():
    for v in (truth.COUNT_FLOOR_USD, 5000.0):
        assert truth.protection_for(pos(market_value=v), broker_available=True)["protection"]["counted"] is True


def test_exempt_never_counted_even_when_unpriced():
    out = truth.protection_for(pos(symbol="SPAXX", market_value=None), broker_available=True)
    assert out["protection_state"] == "EXEMPT" and out["protection"]["counted"] is False
    assert out["protection"]["price_missing"] is False


def test_unpriced_unknown_stays_counted():
    out = truth.protection_for(pos(account_id="moomoo_synth", market_value=None), broker_available=True)
    assert out["protection_state"] == "UNKNOWN" and out["protection"]["counted"] is True


def test_rollup_sees_the_unpriced_gap():
    """End to end into the 2166 Portfolio rollup: the unpriced GAP is a GAP, not silently absent."""
    rows = []
    for p in (pos(symbol="SYNP", market_value=None),
              pos(symbol="SYNA", market_value=5000.0, stop_state="active", stop_source="broker_resting",
                  stop_price=90.0)):
        rows.append({**p, **truth.protection_for(p, broker_available=True)})
    assert [r["protection_state"] for r in rows] == ["GAP", "PROTECTED"]
    out = sp.summary(rows, [])
    assert (out["verdict"], out["gap"], out["counted"], out["listed_not_counted"]) == ("GAP", 1, 2, 0)
