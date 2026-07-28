#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.motion_engine import MotionEngine  # noqa: E402
from active_trader.motion_journal import MotionJournal  # noqa: E402
from active_trader.t2_jit_policy import T2PolicyConfig  # noqa: E402

NOW = 1_753_700_000.0


def _session(symbols="AAPL", **over):
    session = {
        "session_id": "SESS-1",
        "state": "ACTIVE",
        "workflow_mode": "OBSERVE",
        "updated_at": NOW,
        "envelope": {"symbol_list_or_universe_rule": symbols},
    }
    session.update(over)
    return session


def _candidate(**over):
    row = {
        "symbol": "AAPL",
        "observed_at": NOW,
        "setup_state": "FIRED",
        "gate_decision": "PASS",
        "price": 100.0,
        "priority_score": 100.0,
        "source": "test",
    }
    row.update(over)
    return row


def _engine(tmp_path, journal=None):
    return MotionEngine(
        snapshot_path=tmp_path / "snapshot.json",
        state_path=tmp_path / "state.json",
        journal=journal or MotionJournal(tmp_path / "journal.jsonl"),
        t2_config=T2PolicyConfig(
            provider_hard_cap=8,
            max_concurrent_leases=2,
            lease_ttl_s=20,
            min_dwell_s=10,
            cooldown_s=15,
        ),
    )


def test_fired_candidate_gets_t2_only_with_active_symbol_authorized_workflow(tmp_path):
    engine = _engine(tmp_path)
    inactive = engine.tick([_candidate()], session={}, now=NOW)
    assert inactive["t2"]["leases"] == []
    assert inactive["candidates"][0]["admitted"] is False

    active = engine.tick([_candidate()], session=_session(), now=NOW + 1)
    assert len(active["t2"]["leases"]) == 1
    assert active["t2"]["leases"][0]["symbol"] == "AAPL"
    assert active["ui_refresh_after_s"] == 5
    assert active["authority"]["order"] is False
    assert active["session"]["motion_ready"] is True
    assert active["session"]["account_bound"] is False


def test_account_venue_and_environment_do_not_change_motion_admission(tmp_path):
    engine = _engine(tmp_path)
    first = engine.tick(
        [_candidate()],
        session=_session(
            account_id="one",
            venue="broker-a",
            environment="sandbox",
        ),
        now=NOW,
    )
    second = engine.tick(
        [_candidate(observed_at=NOW + 1)],
        session=_session(
            account_id="two",
            venue="broker-b",
            environment="production",
        ),
        now=NOW + 1,
    )
    assert first["t2"]["leases"][0]["symbol"] == "AAPL"
    assert second["t2"]["leases"][0]["symbol"] == "AAPL"
    assert "account_id" not in second["session"]
    assert "venue" not in second["session"]
    assert "environment" not in second["session"]


def test_plain_universe_rule_fails_closed_but_explicit_csv_is_accepted(tmp_path):
    engine = _engine(tmp_path)
    rule = _session("price<20 and rvol>3")
    blocked = engine.tick([_candidate()], session=rule, now=NOW)
    assert blocked["t2"]["leases"] == []

    explicit = engine.tick([_candidate()], session=_session("AAPL,TSLA"), now=NOW + 1)
    assert [row["symbol"] for row in explicit["t2"]["leases"]] == ["AAPL"]


def test_lease_identity_survives_engine_restart(tmp_path):
    journal = MotionJournal(tmp_path / "journal.jsonl")
    first_engine = _engine(tmp_path, journal)
    first = first_engine.tick([_candidate()], session=_session(), now=NOW)
    lease_id = first["t2"]["leases"][0]["lease_id"]

    second_engine = _engine(tmp_path, journal)
    second = second_engine.tick(
        [_candidate(observed_at=NOW + 1)],
        session=_session(),
        now=NOW + 1,
    )
    assert second["t2"]["leases"][0]["lease_id"] == lease_id


def test_position_replay_emits_account_unbound_exit_signal_and_retains_t2(tmp_path):
    journal = MotionJournal(tmp_path / "journal.jsonl")
    observations = [
        {
            "position_id": "P1",
            "symbol": "AAPL",
            "position_open": True,
            "observed_at": NOW + 25,
            "entered_at": NOW,
            "price": 100.8,
            "entry_price": 100.0,
            "hard_stop_price": 98.0,
            "initial_risk_per_share": 2.0,
            "momentum_failure": 0.90,
            "tape_reversal": 0.85,
            "book_weakness": 0.80,
            "structure_failure": 0.80,
            "quote_age_s": 1.0,
            "book_age_s": 1.0,
            "tape_age_s": 1.0,
            "high_watermark": 102.0,
        },
        {
            "position_id": "P1",
            "symbol": "AAPL",
            "position_open": True,
            "observed_at": NOW + 36,
            "entered_at": NOW,
            "price": 100.8,
            "entry_price": 100.0,
            "hard_stop_price": 98.0,
            "initial_risk_per_share": 2.0,
            "momentum_failure": 0.90,
            "tape_reversal": 0.85,
            "book_weakness": 0.80,
            "structure_failure": 0.80,
            "quote_age_s": 1.0,
            "book_age_s": 1.0,
            "tape_age_s": 1.0,
            "high_watermark": 102.0,
        },
        {
            "position_id": "P1",
            "symbol": "AAPL",
            "position_open": True,
            "observed_at": NOW + 47,
            "entered_at": NOW,
            "price": 100.8,
            "entry_price": 100.0,
            "hard_stop_price": 98.0,
            "initial_risk_per_share": 2.0,
            "momentum_failure": 0.90,
            "tape_reversal": 0.85,
            "book_weakness": 0.80,
            "structure_failure": 0.80,
            "quote_age_s": 1.0,
            "book_age_s": 1.0,
            "tape_age_s": 1.0,
            "high_watermark": 102.0,
        },
    ]
    for payload in observations:
        journal.append(
            "position_observation",
            payload,
            recorded_at=payload["observed_at"],
        )

    engine = _engine(tmp_path, journal)
    snapshot = engine.tick([], session=_session(), now=NOW + 47)
    assert snapshot["positions"][0]["state"] == "EXIT_SIGNAL"
    assert snapshot["exit_signals"][0]["signal_only"] is True
    assert snapshot["exit_signals"][0]["automatic_order_sent"] is False
    assert snapshot["exit_signals"][0]["account_bound"] is False
    assert snapshot["exit_signals"][0]["authority"]["order"] is False
    assert snapshot["t2"]["leases"][0]["symbol"] == "AAPL"
    assert snapshot["ui_refresh_after_s"] == 5


def test_missing_observation_time_fails_stale_and_does_not_get_t2(tmp_path):
    engine = _engine(tmp_path)
    snapshot = engine.tick(
        [_candidate(observed_at=None)],
        session=_session(),
        now=NOW,
    )
    assert snapshot["t2"]["leases"] == []
    assert snapshot["candidates"][0]["last_update_age_s"] is None
