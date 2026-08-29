"""EXEC_LINT adjacency: an article was enough to pass the gate.

`place order` matched but `place an order` did not; `execute trade` matched but
`execute the buy` did not. Same failure shape as the memory jailbreak scan
(#631), where `ignore all previous instructions` slipped past a one-qualifier
pattern.

`research_quality.critique` caught `place an order` and this lint caught
`buy now`, so the two nets covered each other's blind spots by accident.
`execute the buy` was covered by neither and attached as VALID.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import pytest

from scripts.lib.hermes_research_schema import lint_execution_language as lint


@pytest.mark.parametrize("text", [
    # the article gap
    "place an order", "place a stop", "submit an order",
    "execute the buy", "execute the trade", "execute the sell", "execute an order",
    # forms that already matched — must keep matching
    "place order", "place stop", "submit order", "execute trade",
    "buy now", "sell now", "market order", "limit order",
    "force fill", "enter long", "enter short",
])
def test_imperative_execution_phrasing_is_caught(text):
    assert lint(text) is not None


@pytest.mark.parametrize("text", [
    "SCHD is an income ballast",
    "management will execute its buyback plan",
    "the order book was thin",
    "revenue execution improved this quarter",
    "the company placed a large contract",
    "",
])
def test_ordinary_analysis_is_not_flagged(text):
    """Rejecting legitimate research silently shrinks coverage."""
    assert lint(text) is None


def test_lint_runs_on_structured_blobs_not_just_strings():
    assert lint({"answers": [{"summary": "execute the buy"}]}) is not None
    assert lint({"answers": [{"summary": "income ballast"}]}) is None


def test_advisory_imperatives_are_now_matched_by_operator_judgment():
    """Resolved 2026-08-29: ban the *instruction*, not the words.

    The earlier version of this test asserted these were NOT matched, and
    recorded the question for the operator. The answer was: "trim the position"
    and "sell half" are instructions, not analysis, so they are rejected — while
    `trim` / `sell` / `half` as vocabulary stay admissible. See
    tests/test_execution_language_shared_gate.py for both halves.
    """
    assert lint("trim the position") is not None
    assert lint("sell half the position") is not None
    # the words themselves remain fine in analysis
    assert lint("a trim would reduce concentration") is None
    assert lint("sold half in 2021") is None
