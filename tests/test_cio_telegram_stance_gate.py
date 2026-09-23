"""Verification for evaluate_cio_stance_gate.

Hard block is only a bullish proposal against CIO AVOID or SELL.
HOLD and epistemic gaps rewrite GO/BUY/ACCUMULATE to WATCH and still send.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.cio_telegram_stance_gate import evaluate_cio_stance_gate  # noqa: E402


def test_avoid_and_sell_trigger_hard_block():
    """Verify AVOID and SELL trigger hard suppression of a bullish GO."""
    for hard_stance in ["AVOID", "SELL"]:
        allow_send, action, reason, _ = evaluate_cio_stance_gate("S", "GO", hard_stance)
        assert allow_send is False
        assert action == "GO"
        assert reason == "cio_stance_conflict"


def test_hold_and_epistemic_gaps_rewrite_go_to_watch():
    """Verify HOLD, RESEARCH_MORE, and HUMAN_REVIEW rewrite GO to WATCH and pass through."""
    for soft_stance in ["HOLD", "RESEARCH_MORE", "HUMAN_REVIEW", "ADD_REVIEW", "NEUTRAL"]:
        allow_send, effective_action, reason, annotation = evaluate_cio_stance_gate(
            "S", "GO", soft_stance,
        )
        assert allow_send is True
        assert effective_action == "WATCH"
        assert reason == ""
        assert f"[CIO Stance: {soft_stance}" in annotation
        assert "Action rewritten to WATCH" in annotation


def test_unstated_rewrites_go_to_watch():
    allow_send, effective_action, reason, annotation = evaluate_cio_stance_gate("S", "GO", None)
    assert allow_send is True
    assert effective_action == "WATCH"
    assert reason == ""
    assert "[CIO Stance: UNSTATED — Action rewritten to WATCH]" in annotation


def test_matching_stance_passes_unchanged():
    """Verify explicit BUY agreement passes without rewrite."""
    allow_send, effective_action, reason, annotation = evaluate_cio_stance_gate("S", "BUY", "BUY")
    assert allow_send is True
    assert effective_action == "BUY"
    assert reason == ""
    assert annotation == ""
