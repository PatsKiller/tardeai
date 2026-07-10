#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from news_symbol_guard import headline_matches_symbol  # noqa: E402


def test_mrln_pasqal_rejected():
    ok, reason = headline_matches_symbol(
        "MRLN",
        "What to Know About Pasqal, the Quantum Start-Up Going Public Soon",
    )
    assert not ok
    assert "foreign_company" in reason


def test_mrln_merlin_accepted():
    ok, _ = headline_matches_symbol(
        "MRLN",
        "Merlin (MRLN) Successfully Concludes Design Review for C-130J Autonomy Program",
    )
    assert ok


def test_mrln_roundup_accepted():
    ok, _ = headline_matches_symbol(
        "MRLN",
        "Nasdaq Futures Dip: NVDA, LULU, MRLN Stocks In Focus",
    )
    assert ok


def test_avoid_tier_headline_guard_same_as_buy():
    """HOLD/AVOID symbols use the same guard — foreign-company noise rejected."""
    ok, reason = headline_matches_symbol(
        "XYZ",
        "What to Know About Pasqal, the Quantum Start-Up Going Public Soon",
    )
    assert not ok
    assert "foreign_company" in reason