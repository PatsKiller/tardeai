#!/usr/bin/env python3
"""proposal_decision_gate BACKTEST_INSUFFICIENT evidence-floor tests.

Thin backtest evidence must NOT silently reach approval: the deliberate
first-sample learning-test path is now opt-in (per-proposal flag or env switch),
default BLOCKED.

    .venv/bin/python -m pytest tests/test_proposal_decision_gate.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import proposal_decision_gate as G  # noqa: E402


def _inputs(**proposal_overrides):
    """Baseline that clears gates 1-5 and lands on BACKTEST_INSUFFICIENT."""
    proposal = {
        "research_score": 90, "confidence_score": 80, "proposed_rr": 2.0,
        "catalyst_verified": True, "catalyst": "earnings",
        "agent_review_status": "complete", "vs_sector_pct": 0.0,
    }
    proposal.update(proposal_overrides)
    technical = {"atr": 1.5, "rsi": 55, "vwap_state": "above",
                 "price_vs_entry_pct": 0.5}
    backtest = {"backtest_quality": "NO_DATA", "sample_size": 0}
    risk_gate = {"approved": True, "result": "APPROVED"}
    return dict(proposal=proposal, technical=technical, backtest=backtest,
                agent_reviews={}, agent_votes={}, llm_review={}, risk_gate=risk_gate)


def test_backtest_insufficient_blocks_by_default(monkeypatch):
    monkeypatch.delenv("PROPOSAL_ALLOW_FIRST_SAMPLE_OVERRIDE", raising=False)
    res = G.compute_decision_state(**_inputs())
    assert res["decision_state"] == "BACKTEST_INSUFFICIENT"
    assert res["approval_allowed"] is False
    assert any("approval blocked" in r for r in res["reasons"])


def test_per_proposal_override_allows(monkeypatch):
    monkeypatch.delenv("PROPOSAL_ALLOW_FIRST_SAMPLE_OVERRIDE", raising=False)
    res = G.compute_decision_state(**_inputs(allow_first_sample_override=True))
    assert res["decision_state"] == "BACKTEST_INSUFFICIENT"
    assert res["approval_allowed"] is True
    assert any("override active" in r for r in res["reasons"])


def test_env_override_allows(monkeypatch):
    monkeypatch.setenv("PROPOSAL_ALLOW_FIRST_SAMPLE_OVERRIDE", "1")
    res = G.compute_decision_state(**_inputs())
    assert res["approval_allowed"] is True


def test_string_flag_is_parsed(monkeypatch):
    monkeypatch.delenv("PROPOSAL_ALLOW_FIRST_SAMPLE_OVERRIDE", raising=False)
    assert G.compute_decision_state(
        **_inputs(allow_first_sample_override="true"))["approval_allowed"] is True
    assert G.compute_decision_state(
        **_inputs(allow_first_sample_override="no"))["approval_allowed"] is False
