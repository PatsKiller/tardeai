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
