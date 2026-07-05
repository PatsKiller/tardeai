#!/usr/bin/env python3
"""Options desk action button gating — blocked cards must not show trade verbs."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import card_semantics as cs  # noqa: E402

TRADE_ACTIONS = {"sell_covered_call", "sell_put", "buy_put", "buy_call", "sell_credit_spread"}


def _actions(proposal: dict) -> set[str]:
    return {b["action"] for b in cs.sanitize_action_buttons(proposal)}


def _blocked_proposal(**extra) -> dict:
    base = {
        "id": "opt_test",
        "strategy": extra.pop("strategy", "covered_call"),
        "status": "blocked",
        "action_buttons": [
            {"action": "sell_covered_call", "label": "Sell Covered Call"},
            {"action": "sell_put", "label": "Sell Put"},
            {"action": "buy_put", "label": "Buy Put (hedge)"},
            {"action": "hold", "label": "Pass"},
        ],
    }
    base.update(extra)
    return base


@pytest.mark.parametrize("strategy,trade_action", [
    ("covered_call", "sell_covered_call"),
    ("cash_secured_put", "sell_put"),
    ("protective_put", "buy_put"),
])
def test_blocked_card_hides_trade_actions(strategy, trade_action):
    p = _blocked_proposal(strategy=strategy)
    p["action_buttons"] = [{"action": trade_action, "label": trade_action}]
    assert cs.is_card_blocked(p)
    acts = _actions(p)
    assert trade_action not in acts
    assert "review_chain" in acts
    assert "review_block_reason" in acts
    assert "rerun_review" in acts
    assert "hold" in acts


def test_blocked_via_enterprise_blocks():
    p = {
        "strategy": "covered_call",
        "enterprise": {"blocks": ["OI zero"]},
        "action_buttons": [{"action": "sell_covered_call", "label": "Sell Covered Call"}],
    }
    assert cs.is_card_blocked(p)
    assert "sell_covered_call" not in _actions(p)


def test_blocked_via_aegis_block():
    p = {
        "strategy": "protective_put",
        "aegis_verdict": "BLOCK",
        "action_buttons": [{"action": "buy_put", "label": "Buy Put"}],
    }
    assert cs.is_card_blocked(p)
    assert "buy_put" not in _actions(p)


def test_non_blocked_manual_fidelity_keeps_review_actions():
    p = {
        "broker": "fidelity",
        "execution_mode": "manual",
        "strategy": "covered_call",
        "action_buttons": [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ],
    }
    assert not cs.is_card_blocked(p)
    out = cs.apply_card_semantics(p)
    assert "Fidelity" in out["execution_note"]
    assert "Schwab live" not in out["execution_note"]


def test_apply_card_semantics_blocked_strips_executed_manually_label():
    p = _blocked_proposal()
    p["action_buttons"].append({"action": "executed_manually", "label": "Executed manually"})
    out = cs.apply_card_semantics(p)
    assert out["card_blocked"] is True
    assert TRADE_ACTIONS.isdisjoint(_actions(out))