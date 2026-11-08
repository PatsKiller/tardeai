"""LQ-20261107-407: an LLM refusal is never a narrative and never a consensus vote."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest

from lib.llm_refusal import is_refusal

REFUSALS = [
    "I cannot perform investment synthesis as the default Hermes profile.",
    "**Refusal** This request requires the active profile to switch to a trading identity.",
    "I am operating in the default Hermes profile and cannot sell anything.",
    "**Hermes Review** I can't help with this.",
    "Hermes default profile active. Declining.",
    "[MULTI-CONSENSUS] lanes disagreed (Grok=SELL); settled on SELL. I cannot perform investment synthesis.",
    "I'm unable to provide a recommendation.",
]
REAL = [
    "ISRG: Q3 results beat; the thesis holds. I cannot ignore valuation, so trim on strength.",
    "Strong revenue growth; recommend HOLD pending earnings.",
    "",
    None,
]


@pytest.mark.parametrize("t", REFUSALS)
def test_refusals_detected(t):
    assert is_refusal(t)


@pytest.mark.parametrize("t", REAL)
def test_real_narratives_kept(t):
    assert not is_refusal(t)


def test_rec_from_refusal_gives_no_vote():
    import process_watchlist_agent_jobs as m

    assert m._rec_from("I cannot perform investment synthesis. I would SELL nothing.") == ("", 0.0)
    assert m._rec_from('{"recommendation":"HOLD","confidence":0.7}')[0] == "HOLD"


def test_writer_uses_shared_predicate():
    import process_watchlist_agent_jobs as m

    assert m._is_refusal("I am operating in the default Hermes profile")


# LQ-20261107-522 review of LQ-512: real analysis that opens with a refusal-looking word. The writer turns a
# refusal verdict into a failed run and a blanked card, so each of these must stay real (precision, not recall).
MUST_STAY_REAL = [
    "Declined 12% since the Q3 print; the support at 41 held, so HOLD.",
    "Refused-tender risk is low: the board accepted the revised offer at 18.40.",
    "I cannot see a catalyst before the Q1 print, so the thesis stays HOLD.",
    "I cannot ignore the margin compression: gross margin fell 340 bp year over year.",
    "As an AI-infrastructure supplier, the company rides hyperscaler capex.",
    "Request outside the normal window: the earnings date moved to after the close.",
    "The current profile is defensive: low beta, a 3.1% yield and net cash.",
    "Hermes review of the 10-Q: revenue grew 14% and guidance was raised.",
]


@pytest.mark.parametrize("t", MUST_STAY_REAL)
def test_refusal_looking_openers_in_real_analysis_stay_real(t):
    assert not is_refusal(t)
