"""Stage 9 tests — shadow decision engine (deterministic, fixtures only)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.shadow_engine import (  # noqa: E402
    DecisionInput, ENGINE_VERSION, FireState, PrimeState, RunnerState,
    evaluate_fire, evaluate_prime, resilience_score, resistance_score,
    run_shadow, runner_state,
)


def base(**over):
    d = dict(symbol="TESTA", as_of_ns=1_000, candidate_state="IN_SCOPE", price=4.2, vwap=4.0,
             session_high=4.19, session_low=3.8, rvol=4.0, spread_bps=10.0, halt_state="NONE",
             capability_ok=True, risk_ok=True, data_state="HEALTHY",
             integrated_ofi=0.4, tape_aggressor_buy=0.62, bid_replenish=8, reclaim_speed=8,
             higher_low=True, ask_replenish=2, failed_breakouts=0)
    d.update(over)
    return DecisionInput(**d)


# ---- prime states
def test_prime_states():
    assert evaluate_prime(base()).state == PrimeState.PRIMED.value
    assert evaluate_prime(base(rvol=1.0)).state == PrimeState.NOT_PRIMED.value
    assert evaluate_prime(base(candidate_state="NO_GO")).state == PrimeState.BLOCKED.value
    assert evaluate_prime(base(halt_state="HALTED")).state == PrimeState.BLOCKED.value
    assert evaluate_prime(base(capability_ok=False)).state == PrimeState.BLOCKED.value
    assert evaluate_prime(base(data_state="STALE")).state == PrimeState.STALE.value
    assert evaluate_prime(base(price=None)).state == PrimeState.INSUFFICIENT_DATA.value


# ---- fire states
def test_fire_states():
    p = evaluate_prime(base())
    assert evaluate_fire(base(price=4.25), p).state == FireState.FIRE_SHADOW.value
    assert evaluate_fire(base(price=4.0, session_high=4.19), evaluate_prime(base(price=4.0))).state \
        == FireState.NO_FIRE.value
    assert evaluate_fire(base(), evaluate_prime(base(rvol=1.0))).state == FireState.NO_FIRE.value
    assert evaluate_fire(base(data_state="SEQUENCE_GAP"), p).state == FireState.DATA_GAP.value
    assert evaluate_fire(base(data_state="STALE"), p).state == FireState.STALE.value
    assert evaluate_fire(base(halt_state="LULD"), p).state == FireState.BLOCKED.value
    # no microstructure -> NO_FIRE, not an error
    assert evaluate_fire(base(integrated_ofi=None), p).state == FireState.NO_FIRE.value


# ---- RES / RRS
def test_res_rrs_ranges_and_confidence():
    res = resilience_score(base())
    rrs = resistance_score(base())
    assert 0 <= res.value <= 100 and 0 <= rrs.value <= 100
    assert res.confidence in ("HIGH", "MEDIUM", "LOW")
    # missing microstructure lowers confidence / may be insufficient
    sparse = resilience_score(base(integrated_ofi=None, tape_aggressor_buy=None, bid_replenish=None,
                                   reclaim_speed=None, higher_low=None, rvol=None, spread_bps=None,
                                   price=None, vwap=None))
    assert sparse.value is None and sparse.confidence == "INSUFFICIENT"


def test_scores_missing_data_handled():
    r = resilience_score(base(integrated_ofi=None))
    assert r.value is not None and r.components["integrated_ofi"] is None


# ---- runner
def test_runner_transitions():
    strong_res = resilience_score(base())
    low_rrs = resistance_score(base(failed_breakouts=0, ask_replenish=0, integrated_ofi=0.5,
                                    tape_aggressor_buy=0.7, spread_bps=5, session_high=99))
    st = runner_state(base(), strong_res, low_rrs)
    assert st.state in (RunnerState.ELIGIBLE.value, RunnerState.ACTIVE.value)
    # high resistance -> EXIT
    from active_trader.shadow_engine import Score, RRS_VERSION
    hi = Score(85.0, RRS_VERSION, "HIGH", {})
    assert runner_state(base(), strong_res, hi).state == RunnerState.EXIT.value
    # low resilience while active -> INVALIDATED
    lo = Score(30.0, "res-1", "HIGH", {})
    assert runner_state(base(), lo, low_rrs, currently_active=True).state == RunnerState.INVALIDATED.value
    # data gap -> DATA_BLOCKED
    assert runner_state(base(data_state="SEQUENCE_GAP"), strong_res, low_rrs).state \
        == RunnerState.DATA_BLOCKED.value


# ---- no lookahead + determinism
def test_no_lookahead_refused():
    with pytest.raises(ValueError, match="lookahead"):
        evaluate_prime(base(contains_future_data=True))
    with pytest.raises(ValueError):
        resilience_score(base(contains_future_data=True))


def test_deterministic_replay_equality():
    a = run_shadow(base())
    b = run_shadow(base())
    # decisions and scores identical
    assert a["prime"] == b["prime"] and a["fire"] == b["fire"]
    assert a["res"] == b["res"] and a["rrs"] == b["rrs"] and a["runner"] == b["runner"]
    assert a["journal"] == b["journal"]


# ---- journal
def test_journal_events_provenance_and_idempotency():
    out = run_shadow(base())
    j = out["journal"]
    assert len(j) == 5
    assert all(e["provenance"] == "SHADOW_FIXTURE_OR_REPLAY" for e in j)
    assert all(e["engine_version"] == ENGINE_VERSION for e in j)
    types = [e["event_type"] for e in j]
    assert types == ["prime_evaluated", "fire_evaluated", "res_scored", "rrs_scored", "runner_evaluated"]
    # replay produces identical journal (idempotent content)
    assert run_shadow(base())["journal"] == j


def test_no_order_or_broker_field():
    out = run_shadow(base())
    blob = str(out)
    for word in ("submit", "place_order", "broker_call", "unlock"):
        assert word not in blob
