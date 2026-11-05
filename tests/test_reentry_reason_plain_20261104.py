"""REENTRY_REASON_PLAIN_20261104 — FQ-002.

Measured on the served release `105df180e` (twice, 17:xxZ): 31 of 149 advisory rows carried

    reentry_state  "MISSING MARKET"
    reentry_reason "Quote present but RSI missing from indicator_confluence_cache — run indicator_cache_refresh
                    for exited symbols."

— an internal table name and a script instruction in operator-facing text, and a state that calls the market
missing while the quote is present.

The override is now a pure function so the behaviour can be asserted rather than grepped: a present price with
no RSI gets a plain reason and action; every other combination is left untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker.reentry_decision_desk import missing_indicators_note  # noqa: E402


def test_a_present_quote_with_no_indicators_says_what_is_missing():
    note = missing_indicators_note("MISSING MARKET", 10.0, None)
    assert note is not None
    assert note["reason"] == ("The price is available but the technical indicators are missing, "
                             "so a re-entry review cannot run yet.")
    assert note["action"] == "Refresh the technical indicators"
    assert "indicator_confluence_cache" not in note["reason"]
    assert "indicator_cache_refresh" not in note["reason"]


def test_no_quote_is_left_to_the_state_machine():
    assert missing_indicators_note("MISSING MARKET", None, None) is None


def test_other_states_are_untouched():
    assert missing_indicators_note("STALE", 10.0, None) is None
    assert missing_indicators_note("WAIT", 10.0, 55.0) is None
    assert missing_indicators_note("MISSING MARKET", 10.0, 55.0) is None


def test_the_module_carries_no_internal_name_in_that_path():
    src = (ROOT / "scripts" / "lib" / "data_broker" / "reentry_decision_desk.py").read_text()
    assert "Quote present but RSI missing" not in src
    assert "run indicator_cache_refresh" not in src
