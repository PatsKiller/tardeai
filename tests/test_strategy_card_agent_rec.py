#!/usr/bin/env python3
"""The synthesis is the authority over agent_rec on strategy cards.

Two defects, found 2026-07-20 by reading a live BETA card that contradicted
itself:

1. The card displayed agent_rec=TRIM beside its own CIO text saying that exact
   TRIM had been discarded. The synthesis rejected steph's hallucinated $1.3M
   position at 13:16; this materializer re-stamped the TRIM at 14:30 and would
   have again every 30 minutes. A rejection a downstream writer overwrites on a
   schedule is worse than the original bad output — the correction can never
   hold.

2. agent_rec was `DISTINCT ON (symbol) ORDER BY created_at DESC`, i.e. whichever
   agent's job finished LAST. On BETA that was steph by 47 seconds over
   risk_agent. It was never an agent view; it was a scheduling race.

The suppression rule must stay NARROW. A first attempt suppressed any agent
merely named in a conflict and blanked agent_rec on 1,025 symbols, because most
conflicts are ordinary disagreement naming everyone. Disagreement is what the
synthesis is FOR.

Pure: the rule is exercised directly. No database, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import materialize_watchlist_strategy_cards as mat  # noqa: E402

SRC = (ROOT / "scripts" / "materialize_watchlist_strategy_cards.py").read_text()


def _discarded(conflicts) -> set:
    """Reimplements the module's per-entry rule against a literal conflicts list."""
    entries = conflicts if isinstance(conflicts, (list, tuple)) else [conflicts]
    out = set()
    for entry in entries:
        text = str(entry).lower()
        if not mat.GROUND_TRUTH_CONTRADICTION.search(text):
            continue
        out |= {a for a in mat.KNOWN_AGENTS if a in text}
    return out


# ── the BETA case must stay caught ────────────────────────────────────────────

BETA_CONFLICT = ("Steph narrative assumes existing 17.3% overweight position and $1.3M "
                 "holding; directly contradicts PORTFOLIO POSITION ground truth of 0 "
                 "shares and $0 value")


def test_beta_ground_truth_contradiction_discards_steph():
    assert _discarded([BETA_CONFLICT]) == {"steph"}


def test_beta_does_not_discard_the_uninvolved_agents():
    d = _discarded([BETA_CONFLICT])
    assert "risk_agent" not in d and "maria" not in d


# ── ordinary disagreement must NOT suppress ───────────────────────────────────

@pytest.mark.parametrize("conflict", [
    "Maria BUY (thesis/fundamentals) vs Steph/Risk AVOID (risk/concentration/momentum)",
    "RISK_AGENT prioritizes portfolio heat and volatility (HOLD); MARIA prioritizes news catalyst (BUY)",
    "Maria advocates BUY on analyst upgrade; RISK_AGENT and STEPH both recommend HOLD due to technical range",
    "Maria BUY (news-driven upgrade to $78 target) vs Risk/Steph HOLD (heat + weak confluence 5/100)",
])
def test_agent_disagreement_is_not_grounds_for_suppression(conflict):
    """~79% of conflict entries are this. Suppressing them blanked 1,025 cards
    and would hide the disagreement signal the desk depends on."""
    assert _discarded([conflict]) == set()


def test_no_conflicts_discards_nothing():
    assert _discarded([]) == set()
    assert _discarded(None if False else []) == set()


# ── per-entry matching ────────────────────────────────────────────────────────

def test_ground_truth_marker_does_not_leak_across_entries():
    """Joining entries first would let a marker in one suppress an agent named
    only in another. Entry 1 discards steph; entry 2 is plain disagreement and
    must not take maria down with it."""
    d = _discarded([BETA_CONFLICT, "Maria BUY vs Risk_Agent HOLD on momentum"])
    assert d == {"steph"}


def test_multiple_ground_truth_entries_accumulate():
    d = _discarded([
        "Steph narrative contradicts PORTFOLIO POSITION ground truth of 0 shares",
        "Maria cites a holding that does not exist — 0 shares held, flag misapplied",
    ])
    assert d == {"steph", "maria"}


# ── the ground-truth vocabulary ───────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "contradicts PORTFOLIO POSITION ground truth",
    "PORTFOLIO POSITION block states 0 shares held",
    "steph assumed a position but no position is held",
    "heat flag appears misapplied or stale to this symbol",
    "the agent hallucinated a holding",
])
def test_ground_truth_phrases_are_recognised(phrase):
    assert mat.GROUND_TRUTH_CONTRADICTION.search(phrase.lower())


@pytest.mark.parametrize("phrase", [
    "maria prioritizes fundamentals while steph prioritizes momentum",
    "risk_agent cites elevated portfolio heat",
    "disagreement on time horizon",
])
def test_ordinary_language_is_not_a_ground_truth_marker(phrase):
    assert not mat.GROUND_TRUTH_CONTRADICTION.search(phrase.lower())


# ── the selection itself ──────────────────────────────────────────────────────

def test_selection_no_longer_uses_a_bare_distinct_on_race():
    assert "DISTINCT ON (symbol) symbol, recommendation, confidence, summary" not in SRC, \
        "the finish-order race is back — agent_rec would again be whichever job ended last"


def test_only_completed_results_with_a_recommendation_are_considered():
    assert "status = 'completed'" in SRC and "recommendation IS NOT NULL" in SRC


def test_provenance_is_recorded_on_the_card():
    """Without agent_rec_agent the finish-order race is invisible; without
    agent_rec_suppressed a suppressed rec looks like it was never produced."""
    for key in ("agent_rec_agent", "agent_rec_suppressed", "agent_rec_authority"):
        assert f'"{key}"' in SRC, f"{key} missing from the card payload"


def test_suppression_is_recorded_once_per_agent():
    """A first cut appended one entry per historical row and produced 53 entries
    for a single symbol, because a fully-suppressed symbol never short-circuits
    the loop."""
    assert "_seen" in SRC and "key not in _seen" in SRC


def test_known_agents_matches_the_live_roster():
    for a in ("maria", "steph", "risk_agent"):
        assert a in mat.KNOWN_AGENTS
    assert all(a == a.lower() for a in mat.KNOWN_AGENTS), "matching is lowercased"
