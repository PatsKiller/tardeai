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

from scripts.lib.agent_memory_provider import LocalTestMemoryProvider  # noqa: E402
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
        "memory_attributable_action_flips": 0,
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


def test_promotion_gate_blocks_on_trace_coverage():
    res = _clean_decision_shadow()
    res["trace_coverage"] = 0.5
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["trace_coverage"] is False


# ── Genuine dual-path decision shadow (P1 regression) ─────────────────────


def _all_traced_wake_file(tmp_path):
    p = tmp_path / "wakes_all_traced.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"wake_id":"w1","trace_id":"t1","phase":"open","outcome":"open"}',
                '{"wake_id":"w2","trace_id":"t2","phase":"close","outcome":"ok"}',
            ]
        )
    )
    return p


def _same_action_evaluator(wake, context, mode):
    # Deterministic injected evaluator (no live LLM). Returns a FRESH dict per
    # invocation, so baseline and augmented are genuinely distinct objects.
    return {
        "decision_id": f"dec_{wake.get('wake_id')}_{mode}",
        "current_action": "HOLD",
        "act_now": False,
        "memory_ids_used": list(
            (context.get("episodic_memory") or {}).get("memory_ids") or []
        ),
    }


def _genuine_clean_result(tmp_path):
    return shadow_compare_wakes(
        _all_traced_wake_file(tmp_path),
        decision_evaluator=_same_action_evaluator,
        evaluator_version="test-v1",
    )


def test_genuine_dual_path_result_is_complete(tmp_path):
    res = _genuine_clean_result(tmp_path)
    assert res["decision_payloads_available"] is True
    assert res["decision_comparisons_completed"] is True
    assert res["dual_path_executed"] is True
    assert res["memory_attributable_action_flips"] == 0
    p = res["packets"][0]
    assert p["comparison_completed"] is True
    assert p["baseline_decision_digest"] != p["augmented_decision_digest"]


def test_promotion_gate_fully_clean_dual_path_promotes(tmp_path):
    res = _genuine_clean_result(tmp_path)
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_PROMOTED
    assert g["all_hard_gates"] is True


def test_promotion_gate_synthetic_packet_without_lineage_not_promoted():
    # A synthetic dict that CLAIMS payloads/comparisons but carries no
    # dual_path_executed lineage must NOT promote.
    res = _clean_decision_shadow()
    res["decision_payloads_available"] = True
    res["decision_comparisons_completed"] = True
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["decision_dual_path"] is False


def test_same_object_returned_for_both_paths_not_complete(tmp_path):
    shared = {"decision_id": "d1", "current_action": "HOLD", "act_now": False}

    def evaluator(wake, context, mode):
        return shared  # SAME object for both paths

    res = shadow_compare_wakes(
        _all_traced_wake_file(tmp_path),
        decision_evaluator=evaluator,
        evaluator_version="test-v1",
    )
    assert res["decision_payloads_available"] is False
    assert res["decision_comparisons_completed"] is False
    assert res["dual_path_executed"] is False


def test_augmented_evaluation_failure_not_promotable(tmp_path):
    def evaluator(wake, context, mode):
        if mode == "augmented":
            raise RuntimeError("boom")
        return {"decision_id": "d1", "current_action": "HOLD", "act_now": False}

    res = shadow_compare_wakes(
        _all_traced_wake_file(tmp_path),
        decision_evaluator=evaluator,
        evaluator_version="test-v1",
    )
    assert res["decision_comparisons_completed"] is False
    assert res["dual_path_executed"] is False
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED


def test_context_only_corpus_never_promotes(tmp_path):
    # No evaluator at all => context-only => NOT_PROMOTED.
    res = shadow_compare_wakes(_all_traced_wake_file(tmp_path))
    assert res["decision_payloads_available"] is False
    assert res["dual_path_executed"] is False
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    assert g["verdict"] == PROMOTION_NOT_PROMOTED


def _flip_memory_provider():
    p = LocalTestMemoryProvider()
    p.add_candidate(
        {
            "memory_type": "OPERATOR_EXPLICIT_PREFERENCE",
            "subject": "SCHD",
            "content": "operator prefers SCHD",
            "source_event_ids": ["evt_1"],
        }
    )
    return p


def test_memory_attributable_flip_is_detected(tmp_path):
    # Baseline HOLD, augmented ADD attributable to a retrieved memory.
    def evaluator(wake, context, mode):
        mem_ids = list((context.get("episodic_memory") or {}).get("memory_ids") or [])
        if mode == "baseline":
            return {"decision_id": "d1", "current_action": "HOLD", "act_now": False, "memory_ids_used": []}
        return {
            "decision_id": "d1",
            "current_action": "ADD" if mem_ids else "HOLD",
            "act_now": bool(mem_ids),
            "memory_ids_used": mem_ids,
        }

    res = shadow_compare_wakes(
        _all_traced_wake_file(tmp_path),
        memory_provider=_flip_memory_provider(),
        decision_evaluator=evaluator,
        evaluator_version="test-v1",
    )
    assert res["memory_attributable_action_flips"] >= 1
    g = promotion_gate(res, behavior_influence_enabled=True, metrics=_clean_metrics())
    # Even with externally-clean metrics, the derived flip blocks promotion.
    assert g["checks"]["shadow_memory_attributable_flips"] is False
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
