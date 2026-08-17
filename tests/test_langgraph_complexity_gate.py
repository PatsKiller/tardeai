"""Phase 8 — langgraph_complexity_gate unit/adversarial tests.

No broker, no network. Deterministic only. Asserts the NOT_REQUIRED default is
a SUCCESS, metrics are deterministic, and no verdict authorizes broker authority.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.langgraph_complexity_gate import (  # noqa: E402
    GATE_NOT_REQUIRED,
    GATE_PILOTED,
    GATE_VALID,
    compute_complexity_metrics,
    gate_decision,
    letta_decision,
)


def _linear_traces():
    return [
        {"wake_id": "w1", "trace_id": "tr_w1", "steps": [{"tool": "read"}, {"tool": "read"}]},
        {"wake_id": "w2", "trace_id": "tr_w2", "steps": [{"tool": "read"}]},
        {"wake_id": "w3", "trace_id": "tr_w3", "steps": [{"tool": "read"}, {"tool": "read"}, {"tool": "read"}]},
    ]


def _complex_trace():
    # Many resumable wait states + retries + branching + a state-loss incident.
    return {
        "wake_id": "wc",
        "trace_id": "tr_wc",
        "durable_wait_count": 3,
        "resume_count": 3,
        "branch_count": 4,
        "retry_count": 5,
        "partial_failure_recovery": 2,
        "manual_recovery_incidents": 1,
        "operator_interrupts": 2,
        "state_loss_incidents": 1,
    }


# ── NOT_REQUIRED default (a SUCCESS, not a failure) ────────────────────────


def test_linear_trace_set_is_not_required():
    metrics = compute_complexity_metrics(_linear_traces())
    assert gate_decision(metrics) == GATE_NOT_REQUIRED
    # Recorded decision inside the metrics matches the standalone call.
    assert metrics["gate_decision"] == GATE_NOT_REQUIRED


def test_empty_trace_set_is_not_required():
    assert gate_decision(compute_complexity_metrics([])) == GATE_NOT_REQUIRED


def test_not_required_is_a_success_not_a_failure():
    # The default gate decision string is exactly "NOT_REQUIRED" (a SUCCESS).
    assert GATE_NOT_REQUIRED == "NOT_REQUIRED"
    assert "NOT_REQUIRED" in GATE_VALID


# ── Deterministic metrics + summed counts ──────────────────────────────────


def test_metrics_deterministic():
    traces = _linear_traces()
    a = compute_complexity_metrics(traces)
    b = compute_complexity_metrics(traces)
    assert a == b


def test_metrics_sum_counts():
    traces = [
        {"wake_id": "w1", "branch_count": 2, "retry_count": 1},
        {"wake_id": "w2", "branch_count": 3, "retry_count": 1},
    ]
    metrics = compute_complexity_metrics(traces)
    assert metrics["branch_count"] == 5
    assert metrics["retry_count"] == 2
    assert metrics["traces"] == 2


def test_avg_steps_per_wake():
    metrics = compute_complexity_metrics(_linear_traces())
    # wake steps: w1=2, w2=1, w3=3 → avg 2.0
    assert metrics["avg_steps_per_wake"] == 2.0


# ── Complex trace set is at least recorded, never broker authority ─────────


def test_complex_trace_set_recorded_and_valid():
    metrics = compute_complexity_metrics([_complex_trace()])
    decision = gate_decision(metrics)
    # The decision is a valid, recorded verdict — either PILOTED or the
    # NOT_REQUIRED default (never a crash, never an out-of-contract string).
    assert decision in {GATE_PILOTED, GATE_NOT_REQUIRED}
    assert decision in GATE_VALID
    # Recorded inside the metrics.
    assert metrics["gate_decision"] in GATE_VALID


def test_complex_trace_set_does_not_authorize_broker_authority():
    metrics = compute_complexity_metrics([_complex_trace()])
    decision = gate_decision(metrics)
    # Authority is always READ_ONLY_ADVISORY; no broker/order/stop authority
    # is ever granted by this gate, regardless of the verdict.
    assert metrics["authority"] == "READ_ONLY_ADVISORY"
    assert "broker" not in decision.lower()
    assert decision not in {"FULL_TRADING", "AUTHORIZED"}


def test_gate_decision_conservative_default():
    # A metrics dict with nothing exceeding thresholds stays NOT_REQUIRED.
    low = {
        "durable_wait_count": 1,
        "resume_count": 1,
        "branch_count": 2,
        "retry_count": 2,
        "partial_failure_recovery": 1,
        "manual_recovery_incidents": 1,
        "operator_interrupts": 1,
        "state_loss_incidents": 0,
    }
    assert gate_decision(low) == GATE_NOT_REQUIRED


# ── Letta decision ─────────────────────────────────────────────────────────


def test_letta_decision_deferred():
    assert letta_decision() == "DEFERRED"
