"""LQ-20261107-191 / RE-6: the news guard's ticker test is the shared exact-symbol matcher.

11-07 replay: 18 of 33 news rows tagged T in three days were Google-News search hits whose title
contained "don't"/"isn't"/"won't". The guard upper-cased the text first, so DON'T read as a T
token. Synthetic tickers and synthetic headlines only.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from news_symbol_guard import headline_matches_symbol  # noqa: E402


@pytest.mark.parametrize("title", [
    "Why investors don't trust this rally",
    "The Fed isn't done yet, strategists say",
    "Stocks won't stay cheap for long",
    "Here’s why the market can’t stop climbing",  # curly apostrophes
])
def test_an_apostrophe_t_is_not_the_ticker_t(title):
    ok, why = headline_matches_symbol("T", title)
    assert not ok, why


def test_a_lower_case_word_is_not_an_upper_case_ticker():
    # "zqx" in prose is not ZQX; the old guard upper-cased the text first.
    ok, why = headline_matches_symbol("ZQX", "the zqx fund family adds a bond sleeve")
    assert not ok, why


@pytest.mark.parametrize("title", [
    "T-Mobile adds 900k subscribers",
    "TELUS (TSX:T) beats estimates",
])
def test_compound_and_foreign_listings_are_not_the_ticker(title):
    ok, why = headline_matches_symbol("T", title)
    assert not ok, why


def test_the_real_ticker_still_matches():
    assert headline_matches_symbol("ZQX", "ZQX jumps 12% after guidance raise") == (True, "ticker_token")
    assert headline_matches_symbol("ZQX", "Why $ZQX could double")[0]
    assert headline_matches_symbol("ZQX", "Zqx Corp (ZQX) raises outlook") == (True, "ticker_paren")


def test_a_single_letter_ticker_is_kept_by_cashtag_or_company_name():
    assert headline_matches_symbol("T", "$T rallies into the close")[0]
    ok, why = headline_matches_symbol("T", "AT&T lifts its free cash flow outlook",
                                      company_description="AT&T Inc. provides telecommunications services.")
    assert ok and why == "company_name"


def test_a_curly_apostrophe_company_name_still_matches_the_profile_name():
    desc = "The Zqxy's Company, together with its subsidiaries, operates restaurants."
    ok, why = headline_matches_symbol("ZQXY", "Zqxy’s rejects takeover proposal", company_description=desc)
    assert ok and why == "company_name"
