#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import t2_jit_policy as t2  # noqa: E402

NOW = 1_753_700_000.0


def _obs(symbol="AAPL", **over):
    raw = {
        "symbol": symbol,
        "observed_at": NOW,
        "session_state": "ACTIVE",
        "setup_state": "ARMED",
        "gate_decision": "PASS",
        "motion_eligible": True,
        "baseline_quote_age_s": 1.0,
        "trigger_distance_bps": 5.0,
        "expected_fire_in_s": 10.0,
        "priority_score": 50.0,
    }
    raw.update(over)
    return t2.CandidateObservation.from_mapping(raw)


def test_far_candidate_stays_t1_and_does_not_consume_t2():
    manager = t2.T2LeaseManager()
    snap = manager.reconcile(
        [_obs(trigger_distance_bps=50.0, expected_fire_in_s=120.0)], now=NOW
    )
    assert snap.leases == ()
    assert snap.decisions[0].tier == t2.TIER_T1
    assert snap.decisions[0].reason_code == t2.R_NOT_NEAR_FIRE
    assert snap.decisions[0].refresh_after_s == 10


def test_near_fire_requires_active_motion_authorized_workflow():
    for change, reason in (
        ({"session_state": "AUTHORIZED"}, t2.R_SESSION_INACTIVE),
        ({"motion_eligible": False}, t2.R_MOTION_INELIGIBLE),
    ):
        manager = t2.T2LeaseManager()
        snap = manager.reconcile([_obs(**change)], now=NOW)
        assert snap.leases == ()
        assert snap.decisions[0].reason_code == reason


def test_account_environment_fields_are_not_part_of_policy():
    manager = t2.T2LeaseManager()
    snap = manager.reconcile(
        [_obs(account_id="acct-any", venue="any", environment="any")],
        now=NOW,
    )
    assert len(snap.leases) == 1
    assert not hasattr(_obs(), "mode")
    assert not hasattr(_obs(), "account_id")


def test_near_fire_candidate_is_admitted_with_push_primary_and_five_second_hint():
    manager = t2.T2LeaseManager()
    snap = manager.reconcile([_obs()], now=NOW)
    assert len(snap.leases) == 1
    assert snap.leases[0].symbol == "AAPL"
    assert snap.decisions[0].tier == t2.TIER_T2
    assert snap.ui_refresh_after_s == 5
    assert snap.push_primary is True
    assert snap.max_pull_fallbacks_per_minute == 2


def test_open_position_gets_priority_and_cannot_be_evicted_by_prefire_candidate():
    cfg = t2.T2PolicyConfig(max_concurrent_leases=1, min_dwell_s=0)
    manager = t2.T2LeaseManager(cfg)
    first = manager.reconcile(
        [_obs("AAPL", position_open=True, setup_state="IN_POSITION", priority_score=0)],
        now=NOW,
    )
    assert first.leases[0].position_open is True

    second = manager.reconcile(
        [
            _obs("AAPL", position_open=True, setup_state="IN_POSITION", priority_score=0),
            _obs("TSLA", setup_state="FIRED", priority_score=999_999),
        ],
        now=NOW + 11,
    )
    assert [lease.symbol for lease in second.leases] == ["AAPL"]
    tsla = next(row for row in second.decisions if row.symbol == "TSLA")
    assert tsla.reason_code == t2.R_CAPACITY


def test_higher_priority_candidate_can_evict_prefire_after_minimum_dwell():
    cfg = t2.T2PolicyConfig(max_concurrent_leases=1, min_dwell_s=10)
    manager = t2.T2LeaseManager(cfg)
    manager.reconcile([_obs("AAPL", priority_score=1)], now=NOW)

    before = manager.reconcile(
        [
            _obs("AAPL", priority_score=1),
            _obs("TSLA", setup_state="FIRED", priority_score=500),
        ],
        now=NOW + 5,
    )
    assert [lease.symbol for lease in before.leases] == ["AAPL"]

    after = manager.reconcile(
        [
            _obs("AAPL", priority_score=1),
            _obs("TSLA", setup_state="FIRED", priority_score=500),
        ],
        now=NOW + 11,
    )
    assert [lease.symbol for lease in after.leases] == ["TSLA"]
    assert any(event.reason_code == t2.R_EVICTED for event in after.events)


def test_invalidation_releases_lease_and_cooldown_prevents_immediate_readmit():
    cfg = t2.T2PolicyConfig(cooldown_s=15)
    manager = t2.T2LeaseManager(cfg)
    manager.reconcile([_obs()], now=NOW)
    invalid = manager.reconcile([_obs(gate_decision="VETO")], now=NOW + 1)
    assert invalid.leases == ()

    cooldown = manager.reconcile([_obs()], now=NOW + 2)
    assert cooldown.leases == ()
    assert cooldown.decisions[0].reason_code == t2.R_COOLDOWN

    admitted = manager.reconcile([_obs()], now=NOW + 17)
    assert len(admitted.leases) == 1


def test_provider_hard_cap_is_never_exceeded():
    cfg = t2.T2PolicyConfig(provider_hard_cap=3, max_concurrent_leases=3)
    manager = t2.T2LeaseManager(cfg)
    snap = manager.reconcile(
        [_obs(f"S{i}", priority_score=i) for i in range(10)], now=NOW
    )
    assert len(snap.leases) == 3
    assert snap.operating_cap == 3
    assert snap.provider_hard_cap == 3


def test_source_is_policy_only_and_contains_no_account_environment_taxonomy():
    src = (ROOT / "scripts" / "active_trader" / "t2_jit_policy.py").read_text(
        encoding="utf-8"
    ).lower()
    forbidden = [
        "import requests",
        "import socket",
        "import urllib",
        "http://",
        "https://",
        "place_order",
        "submit_order",
        "cancel_order",
        "modify_order",
        "unlock_trade",
        "api_key",
        "secret_key",
        "mode_paper",
        "paper/shadow",
        "paper execution",
        "account_not_execution_eligible",
    ]
    assert [token for token in forbidden if token in src] == []
