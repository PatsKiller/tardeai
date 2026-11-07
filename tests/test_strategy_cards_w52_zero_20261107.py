"""LQ-304 (old LQ-57 lane FAIL): a 52-week percentage that makes the divisor zero must not abort the lane run.
COVERS = ["scripts/materialize_watchlist_strategy_cards.py"]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import materialize_watchlist_strategy_cards as M  # noqa: E402


def test_minus_100_percent_is_no_anchor_not_a_crash():
    assert M._range_anchor(10.0, -100) is None
    assert M._range_anchor(10.0, "-100") is None


def test_unusable_percentages_give_none():
    for bad in (-250, float("nan"), float("inf"), float("-inf"), "n/a", None, [1]):
        assert M._range_anchor(10.0, bad) is None


def test_ordinary_percentages_keep_the_old_arithmetic():
    assert M._range_anchor(11.0, 10) == 10.0  # price 10% above the 52-week low
    assert math.isclose(M._range_anchor(9.0, -10), 10.0)  # price 10% below the 52-week high
    assert M._range_anchor(10.0, 0) == 10.0
