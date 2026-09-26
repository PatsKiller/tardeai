"""Stages 2–5: one packet, one lifecycle bucket, honest scorecard. No broker."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.options_decision_packet import build_options_decision_packet
from scripts.lib.options_desk_scorecard import build_scorecard
from scripts.lib.options_lifecycle_primary import primary_bucket, subordinate_buckets


def test_amzn_class_spread_is_not_a_cio_approval():
    row = {
        "symbol": "AMZN",
        "strategy": "credit_spread",
        "account": "schwab_taxable",
        "data_source": "schwab_chain",
        "max_profit": 66,
        "max_loss": 1184,
        "pop_pct": 80,
        "enterprise": {"live_eligible": True, "blocks": []},
        "ensemble_verdict": {"verdict": "PASS"},
        "cio_disposition": "reviewed",
    }
    pkt = build_options_decision_packet(row)
    assert pkt["schema"] == "OptionsDecisionPacket@v1"
    assert pkt["cio_approved"] is False
    assert pkt["operator"]["review_status"] == "unreviewed"
    assert pkt["state"] == "REVIEW_REQUIRED"
    assert pkt["readiness"]["cta"] == "none"
    assert pkt["readiness"]["live_submit"] is False
    assert pkt["estimates"]["reward_to_risk"] == round(66 / 1184, 4)
    assert pkt["comparison"]["comparison"]["preferred_structure"] == "neither"
    assert pkt["model"]["ensemble_present"] is True


def test_blocked_share_shortfall_has_no_cta():
    row = {
        "symbol": "NOC",
        "strategy": "covered_call",
        "account": "schwab_taxable",
        "data_source": "schwab_chain",
        "share_count": 9,
        "underlying_price": 500,
        "stop": 480,
        "enterprise": {"blocks": ["NEED_100_SHARES"]},
    }
    pkt = build_options_decision_packet(
        row, thesis={"thesis_version": "desk@v9", "verdict": "constructive", "direction": "bullish", "evidence_refs": []},
    )
    assert pkt["state"] == "BLOCKED"
    assert pkt["readiness"]["cta"] == "none"


def test_red_harvest_has_one_primary_bucket():
    pos = {
        "decision": {"urgency": "red", "recommendation": "HARVEST_NOW"},
        "economics": {"dte_nearest": 3},
    }
    assert primary_bucket(pos) == "action_now"
    assert "harvest" in subordinate_buckets(pos)
    assert "expiry" in subordinate_buckets(pos)
    assert primary_bucket(pos) not in subordinate_buckets(pos)


def test_scorecard_does_not_validate_zero_closes():
    card = build_scorecard(closed_outcomes=0, open_positions=0, served_sha="751628ccd")
    assert card["outcome_validated"] is False
    assert card["axes"]["learning"] == "not_validated"
    assert card["served_pass"] is False
    assert card["natural_fire_observed"] is False
    assert card["memory_behavior_influence"] == 0
    assert "0/30" in card["paper_gate"]
