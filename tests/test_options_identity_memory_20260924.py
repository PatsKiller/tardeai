#!/usr/bin/env python3
"""Slice A+B — options identity GUIDs + scoped memory envelope.

Hermetic only. No broker, no network, no DB.

    .venv/bin/python -m pytest tests/test_options_identity_memory_20260924.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import options_identity as oid  # noqa: E402
from scripts.lib import options_memory_envelope as ome  # noqa: E402
from scripts.lib import cio_options_fluency as flu  # noqa: E402
from scripts.lib.agent_feature_flags import (  # noqa: E402
    DEFAULT_FLAGS,
    load_feature_flags,
    behavior_influence_active,
)


# ── Slice A — identity ─────────────────────────────────────────────────────


def test_contract_guid_stable_and_distinct():
    a = oid.contract_guid("V", "call", 385, "2026-10-17", venue="schwab")
    b = oid.contract_guid("V", "C", 385.0, "20261017", venue="schwab")
    c = oid.contract_guid("V", "put", 385, "2026-10-17", venue="schwab")
    assert a and a == b
    assert c and c != a


def test_option_strategy_guid_includes_account_and_strategy():
    g1 = oid.option_strategy_guid(
        "covered_call", "V", right="call", strike=385,
        expiration="2026-10-17", venue="schwab", account="schwab_ira",
    )
    g2 = oid.option_strategy_guid(
        "covered_call", "V", right="call", strike=385,
        expiration="2026-10-17", venue="schwab", account="schwab_taxable",
    )
    g3 = oid.option_strategy_guid(
        "long_call", "V", right="call", strike=385,
        expiration="2026-10-17", venue="schwab", account="schwab_ira",
    )
    assert g1 and g2 and g3
    assert g1 != g2  # account scopes strategy instance
    assert g1 != g3  # strategy type scopes


def test_stamp_proposal_identity_idempotent():
    p = {
        "strategy": "covered_call",
        "symbol": "V",
        "underlying": "V",
        "option_type": "call",
        "strike": 385,
        "expiration": "2026-10-17",
        "account": "schwab_ira",
        "broker": "schwab",
    }
    oid.stamp_proposal_identity(p)
    assert p.get("contract_guid")
    assert p.get("option_strategy_guid")
    first = (p["contract_guid"], p["option_strategy_guid"])
    oid.stamp_proposal_identity(p)
    assert (p["contract_guid"], p["option_strategy_guid"]) == first


def test_outcome_attribution_keys_never_invent_pnl():
    keys = oid.outcome_attribution_keys({
        "symbol": "V",
        "strategy": "long_call",
        "option_type": "call",
        "strike": 370,
        "expiration": "2026-11-21",
        "broker": "schwab",
        "account": "paper",
    })
    assert keys["symbol"] == "V"
    assert keys["strategy_id"] == "long_call"
    assert keys.get("option_strategy_guid")
    assert keys.get("contract_guid")
    assert "trade_pnl" not in keys
    assert "pnl" not in keys


def test_build_options_desk_summary_carries_guids():
    """Summary writer surfaces GUIDs when proposals are stamped."""
    # Avoid full generate_proposals — stamp a synthetic proposal through summary.
    from scripts import options_engine as oe

    props = {
        "generated_at": "2026-09-24T20:00:00Z",
        "proposals": [
            oid.stamp_proposal_identity({
                "id": "opt_test",
                "strategy": "long_call",
                "symbol": "V",
                "underlying": "V",
                "option_type": "call",
                "strike": 370,
                "expiration": "2026-11-21",
                "edge_score": 70,
                "pop_pct": 55,
                "account": "paper",
                "broker": "schwab",
                "recommended_action": "Buy Call",
            }),
        ],
        "strategy_overview": {"strategy_slots": {}},
    }
    summary = oe.build_options_desk_summary(props)
    top = summary["top_proposals"][0]
    assert top.get("option_strategy_guid")
    assert top.get("contract_guid")
    by = summary["by_symbol"]["V"][0]
    assert by.get("option_strategy_guid") == top["option_strategy_guid"]


# ── Slice B — scoped memory ────────────────────────────────────────────────


def test_global_memory_influence_default_stays_zero():
    flags = load_feature_flags({})
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert flags["MEMORY_BEHAVIOR_INFLUENCE_OPTIONS"] == 0
    assert behavior_influence_active(flags) is False
    assert DEFAULT_FLAGS["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert DEFAULT_FLAGS["MEMORY_BEHAVIOR_INFLUENCE_OPTIONS"] == 0


def test_scoped_flag_off_no_influence():
    env = ome.build_options_memory_envelope(
        "V",
        flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 0},
        outcomes=[{"symbol": "V", "strategy": "long_call", "outcome": "win", "pnl": 120}],
        learning_notes=[{"symbol": "V", "note": "prefer debit over CC for entry"}],
    )
    assert env["applied"] is False
    assert env["reason"] == "FLAG_OFF"
    assert env["prose"] == ""
    assert env["sources"] == []


def test_scoped_flag_on_empty_fail_closed():
    env = ome.build_options_memory_envelope(
        "V",
        flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
        outcomes=[],
        learning_notes=[],
    )
    assert env["applied"] is False
    assert env["reason"] == "EMPTY"
    assert env["prose"] == ""


def test_scoped_flag_on_with_prior_cites_memory():
    outcomes = [
        {
            "symbol": "V",
            "strategy": "long_call",
            "outcome": "win",
            "pnl": 85.5,
            "option_strategy_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    ]
    notes = [
        {"symbols": ["V"], "note": "Visa entry: prefer long_call over covered_call"},
    ]
    env = ome.build_options_memory_envelope(
        "V",
        flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
        outcomes=outcomes,
        learning_notes=notes,
    )
    assert env["applied"] is True
    assert env["reason"] == "APPLIED"
    assert "options_prior_outcomes" in env["sources"]
    assert "cio_operator_learning" in env["sources"]
    assert "long_call" in env["prose"]
    assert "prefer long_call" in env["prose"]
    assert "Sources:" in env["prose"]
    # Global MBI never flipped by this module
    assert env["memory_behavior_influence_global"] == 0


def test_fluency_opinion_cites_memory_when_applied():
    desk = {
        "generated_at": "2026-09-24T20:00:00Z",
        "strategy_counts": {"long_call": 1},
        "by_symbol": {
            "V": [{
                "strategy": "long_call",
                "strike": 370,
                "option_strategy_guid": "11111111-2222-3333-4444-555555555555",
                "contract_guid": "66666666-7777-8888-9999-aaaaaaaaaaaa",
            }],
        },
    }
    facts = flu.gather_options_house_facts(
        ["V"],
        desk=desk,
        goals=[],
        memory_outcomes=[{
            "symbol": "V", "strategy": "long_call", "outcome": "win", "pnl": 40,
        }],
        memory_notes=[{"symbol": "V", "note": "debit preferred for BUY_READY"}],
        memory_flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 1},
    )
    assert facts["memory_envelope"]["applied"] is True
    card = flu.format_cio_options_opinion(
        facts, symbols=["V"], memory_envelope=facts["memory_envelope"],
    )
    assert "What we learned" in card
    assert "debit preferred" in card
    assert "strategy_guid=11111111" in card
    assert "Sources:" in card


def test_fluency_opinion_no_memory_when_flag_off():
    desk = {"by_symbol": {"V": [{"strategy": "long_call", "strike": 370}]},
            "strategy_counts": {}}
    facts = flu.gather_options_house_facts(
        ["V"],
        desk=desk,
        goals=[],
        memory_outcomes=[{"symbol": "V", "strategy": "long_call", "outcome": "win"}],
        memory_flags={"MEMORY_BEHAVIOR_INFLUENCE_OPTIONS": 0},
    )
    assert facts["memory_envelope"]["applied"] is False
    card = flu.format_cio_options_opinion(
        facts, symbols=["V"], memory_envelope=facts["memory_envelope"],
    )
    assert "What we learned" not in card
