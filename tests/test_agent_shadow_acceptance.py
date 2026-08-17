"""Phase 11 — shadow acceptance (shadow_compare_wakes + promotion_gate) tests.

The promotion gate is FAIL-CLOSED: context-only shadow replay can NEVER justify
behavior influence, and every hard gate requires *measured* evidence. "Not
measured" is a failure, never a PASS.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_shadow_acceptance import (  # noqa: E402
    PROMOTION_NOT_PROMOTED,
    PROMOTION_PROMOTED,
    promotion_gate,
    shadow_compare_wakes,
)


def _wake_file(tmp_path):
    p = tmp_path / "wakes.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"wake_id":"w1","trace_id":"t1","phase":"open","outcome":"open"}',
                '{"wake_id":"w2","trace_id":"t2","phase":"close","outcome":"ok"}',
                '{"wake_id":"w3","phase":"open","outcome":"open"}',
            ]
        )
    )
    return p


# A fully-populated, clean decision-level shadow result + measured metrics that
# satisfies every hard gate. Used to prove a *legitimate* PROMOTE is possible.
def _clean_decision_shadow():
    return {
        "wakes": 100,
        "context_build_failures": 0,
        "trace_coverage": 1.0,
        "packets": [
            {
                "wake_id": "w1",
                "decision_compared": True,
                "shadow_diff": {"action_changed": False},
            }
        ],
        "truth_overrides": 0,
        "decision_payloads_available": True,
        "decision_comparisons_completed": True,
        "critical_memory_false_positives": 0,
    }


def _clean_metrics():
    return {
        "canonical_truth_overrides": 0,
        "unauthorized_actions": 0,
        "critical_memory_false_positives": 0,
        "operator_rejection_recall": 1.0,
        "mcp_write_attempts": 5,
        "mcp_write_denied": 5,
    }


def test_shadow_compare_wakes_counts_and_coverage(tmp_path):
    res = shadow_compare_wakes(_wake_file(tmp_path))
    assert res["wakes"] == 3
    assert res["context_build_failures"] == 0
    assert res["trace_coverage"] == pytest.approx(2 / 3, abs=1e-3)
    assert len(res["packets"]) == 3


def test_shadow_compare_wakes_reports_no_decision_payloads(tmp_path):
    res = shadow_compare_wakes(_wake_file(tmp_path))
    assert res["decision_payloads_available"] is False
    assert res["decision_comparisons_completed"] is False


def test_shadow_compare_packet_shape(tmp_path):
    res = shadow_compare_wakes(_wake_file(tmp_path))
    p = res["packets"][0]
    for key in ("wake_id", "baseline_context_digest", "augmented_context_digest", "same_context", "memory_ids_retrieved", "mcp_used"):
        assert key in p


def test_promotion_gate_context_only_never_promotes():
    # Context-only shadow (no decision payloads) => NOT_PROMOTED even with
    # influence enabled and clean metrics.
    res = _clean_decision_shadow()
    res["decision_payloads_available"] = False
    res["decision_comparisons_completed"] = False
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["decision_evidence"] is False


def test_promotion_gate_influence_on_no_payloads_not_promoted():
    # The original defect: influence=true + no decision payloads must NOT promote.
    res = {"truth_overrides": 0, "trace_coverage": 1.0, "packets": []}
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED


def test_promotion_gate_missing_metrics_not_promoted():
    # No measured metrics => fail closed on every measured gate.
    res = _clean_decision_shadow()
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=None)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    for key in ("canonical_truth_override", "unauthorized_action", "critical_memory_false_positive", "operator_rejection_recall", "mcp_write_attempts_denied"):
        assert g["checks"][key] is False


def test_promotion_gate_missing_operator_recall_not_promoted():
    res = _clean_decision_shadow()
    m = _clean_metrics()
    del m["operator_rejection_recall"]
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=m)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["operator_rejection_recall"] is False


def test_promotion_gate_missing_unauthorized_not_promoted():
    res = _clean_decision_shadow()
    m = _clean_metrics()
    del m["unauthorized_actions"]
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=m)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["unauthorized_action"] is False


def test_promotion_gate_mcp_denial_rate_checked():
    # 5 attempted, only 4 denied => NOT_PROMOTED (denial rate != 100%).
    res = _clean_decision_shadow()
    m = _clean_metrics()
    m["mcp_write_denied"] = 4
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=m)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["mcp_write_attempts_denied"] is False


def test_promotion_gate_one_unauthorized_write_not_promoted():
    res = _clean_decision_shadow()
    m = _clean_metrics()
    m["unauthorized_actions"] = 1
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=m)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["unauthorized_action"] is False


def test_promotion_gate_one_truth_override_not_promoted():
    res = _clean_decision_shadow()
    m = _clean_metrics()
    m["canonical_truth_overrides"] = 1
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=m)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED


def test_promotion_gate_one_memory_false_positive_not_promoted():
    res = _clean_decision_shadow()
    m = _clean_metrics()
    m["critical_memory_false_positives"] = 1
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=m)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED


def test_promotion_gate_influence_off_not_promoted_even_clean():
    res = _clean_decision_shadow()
    g = promotion_gate(res, behavior_influence_enabled=False, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["behavior_influence_enabled"] is False


def test_promotion_gate_fully_clean_promotes():
    res = _clean_decision_shadow()
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_PROMOTED
    assert g["all_hard_gates"] is True


def test_promotion_gate_blocks_on_trace_coverage():
    res = _clean_decision_shadow()
    res["trace_coverage"] = 0.5
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["trace_coverage"] is False
