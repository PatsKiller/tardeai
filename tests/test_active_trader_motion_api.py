#!/usr/bin/env python3
"""Aggregate motion endpoint + shadow assembly: contract, UI-normalizer parity,
read-only / fail-closed / no-write guarantees."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import motion_api  # noqa: E402
from active_trader import motion_shadow as shadow  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI  # noqa: E402
from active_trader.read_http import dispatch  # noqa: E402

NOW = 1_753_700_000.0
MOTION_PATH = "/api/v3/active-trader/motion"
MOTION_CONTRACT = "active-trader-motion-snapshot-v1"

# ── observation fixtures ────────────────────────────────────────────────────
def _t2_candidate(symbol="AAA"):
    # eligible + near fire -> admitted -> T2 lease
    return {
        "symbol": symbol, "observed_at": NOW, "session_state": "ACTIVE",
        "setup_state": "ARMED", "gate_decision": "PASS", "motion_eligible": True,
        "baseline_quote_age_s": 1.0, "trigger_distance_bps": 5.0, "expected_fire_in_s": 10.0,
    }


def _t1_candidate(symbol="BBB"):
    # eligible but not near fire -> tier T1 (near-fire monitored)
    return {
        "symbol": symbol, "observed_at": NOW, "session_state": "ACTIVE",
        "setup_state": "ARMED", "gate_decision": "PASS", "motion_eligible": True,
        "baseline_quote_age_s": 1.0,
    }


def _idle_candidate(symbol="CCC"):
    # motion not authorized -> tier T0 (idle)
    return {
        "symbol": symbol, "observed_at": NOW, "session_state": "ACTIVE",
        "setup_state": "ARMED", "gate_decision": "PASS", "motion_eligible": False,
        "baseline_quote_age_s": 1.0,
    }


def _healthy_position(symbol="POS"):
    return {
        "symbol": symbol, "observed_at": NOW, "entered_at": NOW - 100,
        "price": 10.0, "entry_price": 9.5, "hard_stop_price": 9.0,
        "initial_risk_per_share": 0.5,
        "momentum_failure": 0.0, "tape_reversal": 0.0, "book_weakness": 0.0,
        "structure_failure": 0.0, "quote_age_s": 1.0, "book_age_s": 1.0, "tape_age_s": 2.0,
    }


def _hard_stop_position(symbol="STOP"):
    p = _healthy_position(symbol)
    p["price"] = 8.9  # <= hard_stop_price 9.0 -> immediate EXIT_SIGNAL
    return p


# ── UI-normalizer parity (mirror of normalizeMotion.ts required keys) ────────
LEASE_KEYS = {"lease_id", "symbol", "admitted_at", "renewed_at", "expires_at", "priority", "position_open"}
DECISION_KEYS = {"symbol", "tier", "admitted", "reason_code", "refresh_after_s", "priority"}
POSITION_KEYS = {
    "symbol", "state", "action", "reason_code", "score", "confirmations",
    "drawdown_from_high_r", "armed_for_s", "fire_for_s", "recovery_for_s",
    "refresh_after_s", "price", "entry_price", "hard_stop_price",
    "high_watermark", "evidence_age_s",
}
EXIT_SIGNAL_KEYS = {"symbol", "state", "reason_code", "at"}


def _assert_ui_normalizer_parity(snap):
    """Every item must carry the snake_case keys the UI normalizer picks first."""
    for lease in snap["t2"]["leases"]:
        assert LEASE_KEYS <= set(lease), f"lease missing keys: {LEASE_KEYS - set(lease)}"
    for decision in snap["t2"]["decisions"]:
        assert DECISION_KEYS <= set(decision), f"decision missing: {DECISION_KEYS - set(decision)}"
    for pos in snap["positions"]:
        assert POSITION_KEYS <= set(pos), f"position missing: {POSITION_KEYS - set(pos)}"
    for sig in snap["exit_signals"]:
        assert EXIT_SIGNAL_KEYS <= set(sig), f"exit_signal missing: {EXIT_SIGNAL_KEYS - set(sig)}"


# ── assembly / contract ─────────────────────────────────────────────────────
def test_assembled_snapshot_satisfies_contract():
    snap = shadow.assemble_motion_snapshot(
        [_t2_candidate()], [_healthy_position()], now=NOW
    )
    assert snap["contract"] == MOTION_CONTRACT
    assert snap["t2"]["operating_cap"] == 2
    assert snap["t2"]["provider_hard_cap"] == 8
    assert snap["max_pull_fallbacks_per_minute"] == 2
    assert snap["push_primary"] is True
    assert snap["read_only"] is True and snap["write"] is False
    assert snap["authority"] == {
        "mutation": False, "order": False, "session_authorize": False,
        "canary": False, "financial_action": False,
    }
    # JSON-serializable with no inf/nan
    json.dumps(snap, allow_nan=False)
    _assert_ui_normalizer_parity(snap)


def test_t2_lease_admitted_and_shapes():
    snap = shadow.assemble_motion_snapshot([_t2_candidate()], [], now=NOW)
    assert len(snap["t2"]["leases"]) == 1
    lease = snap["t2"]["leases"][0]
    assert lease["symbol"] == "AAA" and lease["position_open"] is False
    _assert_ui_normalizer_parity(snap)


def test_ui_refresh_5_when_lease_or_position():
    lease_only = shadow.assemble_motion_snapshot([_t2_candidate()], [], now=NOW)
    assert lease_only["ui_refresh_after_s"] == 5
    pos_only = shadow.assemble_motion_snapshot([], [_healthy_position()], now=NOW)
    assert pos_only["ui_refresh_after_s"] == 5


def test_ui_refresh_10_when_near_fire_t1_only():
    snap = shadow.assemble_motion_snapshot([_t1_candidate()], [], now=NOW)
    assert snap["ui_refresh_after_s"] == 10
    assert not snap["t2"]["leases"]
    assert any(d["tier"] == "T1" for d in snap["t2"]["decisions"])


def test_ui_refresh_30_when_idle():
    snap = shadow.assemble_motion_snapshot([_idle_candidate()], [], now=NOW)
    assert snap["ui_refresh_after_s"] == 30
    assert not snap["t2"]["leases"]
    assert all(d["tier"] != "T1" for d in snap["t2"]["decisions"])


def test_exit_signal_is_evidence_only_in_payload():
    snap = shadow.assemble_motion_snapshot([], [_hard_stop_position()], now=NOW)
    assert len(snap["exit_signals"]) == 1
    sig = snap["exit_signals"][0]
    assert sig["symbol"] == "STOP" and sig["state"] == "EXIT_SIGNAL"
    assert sig["reason_code"] == "hard_stop_breached"
    # the payload exposes the signal; authority stays entirely false (never acted on)
    assert snap["authority"]["order"] is False
    assert snap["positions"][0]["state"] == "EXIT_SIGNAL"
    _assert_ui_normalizer_parity(snap)


# ── endpoint: journal-backed read ───────────────────────────────────────────
def test_endpoint_absent_journal_fails_closed(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    body = motion_api.motion_snapshot(now=NOW, path=p)
    # honest unavailable: NOT the live motion contract -> UI contractOk false
    assert body["contract"] != MOTION_CONTRACT
    assert body["available"] is False
    assert body["data_state"] == "MOTION_API_UNAVAILABLE"
    # nothing fabricated
    assert body["positions"] == [] and body["exit_signals"] == []
    assert body["t2"]["leases"] == [] and body["t2"]["decisions"] == []
    assert body["read_only"] is True and body["write"] is False
    assert all(v is False for v in body["authority"].values())


def test_endpoint_returns_fresh_snapshot(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    shadow.run_shadow_cycle(
        now=NOW, path=p, max_lines=None,
        candidate_observations=[_t2_candidate()],
        momentum_observations=[_healthy_position()],
    )
    body = motion_api.motion_snapshot(now=NOW + 1, path=p)
    assert body["contract"] == MOTION_CONTRACT
    assert body["stale"] is False
    assert body["last_update_age_s"] == 1.0
    assert body["read_only"] is True and body["write"] is False
    assert all(v is False for v in body["authority"].values())
    _assert_ui_normalizer_parity(body)


def test_endpoint_stale_marker(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    shadow.run_shadow_cycle(
        now=NOW, path=p, max_lines=None,
        candidate_observations=[_t2_candidate()], momentum_observations=[],
    )
    body = motion_api.motion_snapshot(now=NOW + 9_999, path=p)
    # last-good snapshot preserved (old generated_at) + honest stale marker
    assert body["contract"] == MOTION_CONTRACT
    assert body["stale"] is True
    assert body["data_state"] == "DATA_STALE"
    assert body["generated_at"] == NOW  # not bumped / fabricated


def test_get_path_performs_no_write(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    shadow.run_shadow_cycle(
        now=NOW, path=p, max_lines=None,
        candidate_observations=[_t2_candidate()], momentum_observations=[],
    )
    before = p.read_bytes()
    for _ in range(3):
        motion_api.motion_snapshot(now=NOW + 1, path=p)
    assert p.read_bytes() == before  # the read never mutated the journal


# ── HTTP dispatch ───────────────────────────────────────────────────────────
def test_dispatch_motion_get_ok(tmp_path, monkeypatch):
    p = tmp_path / "motion_journal.jsonl"
    monkeypatch.setenv("ACTIVE_TRADER_MOTION_JOURNAL", str(p))
    shadow.run_shadow_cycle(
        path=p, max_lines=None,
        candidate_observations=[_t2_candidate()], momentum_observations=[],
    )
    api = ReadOnlyActiveTraderAPI()
    status, body = dispatch(api, "GET", MOTION_PATH)
    assert status == 200
    assert body["read_only"] is True and body["write"] is False


def test_dispatch_motion_post_is_405():
    api = ReadOnlyActiveTraderAPI()
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        status, body = dispatch(api, method, MOTION_PATH)
        assert status == 405
        assert body["write"] is False


def test_dispatch_motion_fail_closed_503(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("policy exploded")

    monkeypatch.setattr(motion_api, "motion_snapshot", _boom)
    api = ReadOnlyActiveTraderAPI()
    status, body = dispatch(api, "GET", MOTION_PATH)
    assert status == 503
    assert body["read_only"] is True and body["write"] is False
    assert body["status_hint"] == 503


def test_dispatch_absent_journal_still_200_unavailable(tmp_path, monkeypatch):
    # endpoint absent-journal path returns 200 with an honest unavailable body
    monkeypatch.setenv("ACTIVE_TRADER_MOTION_JOURNAL", str(tmp_path / "nope.jsonl"))
    api = ReadOnlyActiveTraderAPI()
    status, body = dispatch(api, "GET", MOTION_PATH)
    assert status == 200
    assert body["available"] is False
    assert body["positions"] == []
