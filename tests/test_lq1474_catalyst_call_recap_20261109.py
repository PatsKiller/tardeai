"""ANCHOR: LQ1474_CATALYST_CALL_RECAP_20261109. LQ-20261107-1474.

An earnings-call transcript or highlights piece is not an earnings beat because the body
says "beat" or "record revenue". A configured acronym ticker is not the issuer unless the
headline names the company or writes the parenthetical symbol. Patterns live in
config/news_to_catalyst_guards.json. Synthetic text only.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _cc():
    return importlib.import_module("catalyst_classifier")


def _classify(title, summary=""):
    return _cc().classify(title, summary, allow_llm=False)["catalyst_type"]


def test_guard_file_holds_the_call_recap_rule_and_the_aca_issuer():
    doc = json.loads((ROOT / "config" / "news_to_catalyst_guards.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "NewsToCatalystGuards@v1"
    assert "earnings call" in doc["call_recap_headline_patterns"]
    assert "earnings_beat" in doc["headline_only_types_on_call_recap"]
    assert "record (revenue|earnings|profit)" in doc["retired_patterns"]
    aca = next(row for row in doc["acronym_instruments"] if row["symbol"] == "ACA")
    assert "arcosa" in [n.lower() for n in aca["issuer_names"]]


def test_an_earnings_call_highlights_body_is_not_an_earnings_beat():
    kind = _classify(
        "SmartRent Q3 Earnings Call Highlights",
        "The company beat expectations and posted record revenue in the quarter.",
    )
    assert kind != "earnings_beat"
    assert kind == "earnings_call"


def test_a_transcript_body_that_mentions_a_beat_is_not_an_earnings_beat():
    kind = _classify(
        "AXT (AXTI) Q3 2026 Earnings Call Transcript",
        "An analyst asked whether the team can beat the estimate next year. Management declined.",
    )
    assert kind == "earnings_call"


def test_record_revenue_alone_is_not_an_earnings_beat():
    kind = _classify("Example Corp posts record revenue and record profit", "")
    assert kind != "earnings_beat"


def test_a_headline_that_states_the_beat_is_still_an_earnings_beat():
    assert _classify("Example Corp beats estimates for the quarter", "") == "earnings_beat"
    assert _classify("QNT Q3 Earnings Beat Estimates, revenue surges", "") == "earnings_beat"


def test_a_call_headline_that_states_raised_guidance_is_a_guidance_raise():
    kind = _classify(
        "Aehr Test Systems Earnings Call Highlights: Record Revenue, Raised Guidance",
        "The transcript also mentioned a small acquisition from last year.",
    )
    assert kind == "guidance_raise"


def test_a_generic_results_headline_still_reads_the_body():
    kind = _classify(
        "Example Corp reports third-quarter results",
        "The company posted a revenue beat and raised guidance for the year.",
    )
    assert kind == "guidance_raise"


def test_aca_the_statute_is_not_the_arcosa_ticker():
    cc = _cc()
    assert cc.acronym_symbol_conflict("ACA", "3 Healthcare Stocks for Expanded Medicaid and ACA Coverage") == (
        "acronym_not_issuer"
    )
    assert cc.acronym_symbol_conflict("ACA", "Arcosa (ACA) Stock May Look Fully Valued After a Takeover") is None
    assert cc.acronym_symbol_conflict("ACA", "Why Arcosa Inc offers a merger arbitrage opportunity") is None


def test_the_lane_counts_an_acronym_conflict_as_excluded():
    n2c = importlib.import_module("news_to_catalyst")
    assert n2c._acronym_block("ACA", "Healthcare Stocks After the Democratic Win: Medicaid and ACA in Focus") == (
        "acronym_not_issuer"
    )
    assert n2c._acronym_block("ACA", "Arcosa (ACA) agrees to a takeover") is None
