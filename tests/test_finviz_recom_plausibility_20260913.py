"""A 1-5 recommendation scale must refuse values that are not on it.

Found 2026-09-13 while checking what an operator-question responder would have
answered. The operator asked "what are analysts saying about Walmart" and the
backing table said:

    WMT   analyst_rating = 'Strong Sell'   recom_score = 351.79

Finviz recom is a 1-5 scale. 351.79 is a PERCENTAGE that ended up in the
recommendation column when the upstream view's columns moved. The parser did

    rs = float(str(recom_raw).replace("%","").strip())

so the "%" -- the one signal that this was the wrong field -- was stripped, and
351.79 mapped straight onto "anything >= 4.5 is Strong Sell".

Scale of it, measured before the fix:

    last 30 days   5,774 out-of-range vs 105 valid
    since 2026-04  ~81,000 out-of-range vs ~1,800 valid
    EVERY out-of-range row rendered 'Strong Sell'

Yahoo had the same stock at recommendation 'buy', target mean 137.98, 40
analysts. So ~98% of the consensus data had been asserting the opposite of the
other source, for five months, off a misparsed column.

These tests use the real observed values.
"""

from __future__ import annotations

import pytest

from scripts.finviz_enrichment import _classify_recom


# Values seen in the live table on 2026-09-10
REAL_CORRUPT = ["351.79%", "20.51%", "134.92%", "197.11%", "35.42%", "350.96%", "91.27%"]


@pytest.mark.parametrize("raw", REAL_CORRUPT)
def test_percent_values_are_refused_not_laundered(raw):
    """NEGATIVE CONTROL: every one of these rendered 'Strong Sell' before."""
    score, rating, reason = _classify_recom(raw)
    assert score is None
    assert rating is None, f"{raw} must not produce a rating at all"
    assert reason == "percent_sign_not_a_1_5_rating"


def test_the_walmart_case_specifically():
    """The exact value that would have answered the operator's question."""
    score, rating, reason = _classify_recom("351.79%")
    assert rating != "Strong Sell"
    assert rating is None


def test_out_of_range_without_a_percent_sign_is_still_refused():
    """Stripping the '%' upstream must not smuggle the value through."""
    score, rating, reason = _classify_recom("351.79")
    assert score is None and rating is None
    assert reason.startswith("out_of_range_")


@pytest.mark.parametrize("raw,expected", [
    ("1.0", "Strong Buy"), ("1.49", "Strong Buy"),
    ("1.5", "Buy"), ("2.49", "Buy"),
    ("2.5", "Hold"), ("3.49", "Hold"),
    ("3.5", "Sell"), ("4.49", "Sell"),
    ("4.5", "Strong Sell"), ("5.0", "Strong Sell"),
])
def test_genuine_ratings_still_map_exactly_as_before(raw, expected):
    """POSITIVE CONTROL: the mapping for real 1-5 values is unchanged, including
    every boundary. A fix that also moved the thresholds would be a second,
    silent change."""
    score, rating, reason = _classify_recom(raw)
    assert rating == expected
    assert score == pytest.approx(float(raw))
    assert reason is None


def test_a_real_strong_sell_is_still_reachable():
    """The point is not that 'Strong Sell' is banned -- it is that it must be
    earned by a value actually on the scale."""
    _, rating, _ = _classify_recom("4.8")
    assert rating == "Strong Sell"


@pytest.mark.parametrize("raw", ["", "  ", "n/a", "-", None])
def test_junk_is_refused_with_a_reason(raw):
    score, rating, reason = _classify_recom(raw)
    assert score is None and rating is None
    assert reason


def test_boundaries_of_the_scale_are_inclusive():
    assert _classify_recom("1.0")[1] is not None
    assert _classify_recom("5.0")[1] is not None
    assert _classify_recom("0.99")[1] is None
    assert _classify_recom("5.01")[1] is None
