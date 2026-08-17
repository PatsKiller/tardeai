"""Deterministic AIF ↔ Financial Senses dry replay."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.aif_financial_senses_replay import WAKES, run_replay


def test_replay_is_deterministic_and_inert():
    a = run_replay()
    b = run_replay()
    assert a["wake_count"] == len(WAKES)
    assert a["baseline_hash"] == b["baseline_hash"]
    assert a["augmented_hash"] == b["augmented_hash"]
    assert a["behavior_influence"] is False
    assert a["memory_behavior_influence"] == 0
    inv = a["invariants"]
    assert inv["execution_actions_changed"] == 0
    assert inv["broker_calls"] == 0
    assert inv["order_calls"] == 0
    assert inv["stop_mutations"] == 0
    assert inv["two_fa_mutations"] == 0
    assert inv["risk_policy_mutations"] == 0
    assert inv["memory_behavior_flips"] == 0
    assert inv["auto_promotions"] == 0
    assert inv["unsupported_fact_promotions"] == 0
    assert inv["invalid_quality_accepts"] == 0
    assert inv["invalid_freshness_accepts"] == 0
    assert inv["financial_senses_attributable_action_flips"] == 0
    for wake in a["wakes"]:
        assert wake["shadow_only"] is True
        assert wake["behavior_influence"] is False
        assert wake["fs_items"] >= 1
        assert wake["shadow_compare"]["same"] is True
