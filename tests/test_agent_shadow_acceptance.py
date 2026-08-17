"""Phase 11 — shadow acceptance (shadow_compare_wakes + promotion_gate) tests."""
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


def test_shadow_compare_wakes_counts_and_coverage(tmp_path):
    res = shadow_compare_wakes(_wake_file(tmp_path))
    assert res["wakes"] == 3
    assert res["context_build_failures"] == 0
    assert res["trace_coverage"] == pytest.approx(2 / 3, abs=1e-3)
    assert len(res["packets"]) == 3


def test_shadow_compare_packet_shape(tmp_path):
    res = shadow_compare_wakes(_wake_file(tmp_path))
    p = res["packets"][0]
    for key in ("wake_id", "baseline_context_digest", "augmented_context_digest", "same_context", "memory_ids_retrieved", "mcp_used"):
        assert key in p


def test_promotion_gate_conservative_default():
    # Behavior influence is OFF by default -> never promoted.
    res = {"truth_overrides": 0, "trace_coverage": 1.0, "packets": []}
    g = promotion_gate(res)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["all_hard_gates"] is True  # hard gates pass, but influence is off


def test_promotion_gate_promotes_only_when_enabled_and_clean():
    res = {"truth_overrides": 0, "trace_coverage": 1.0, "packets": []}
    g = promotion_gate(res, behavior_influence_enabled=True)
    assert g["verdict"] == PROMOTION_PROMOTED
    assert g["all_hard_gates"] is True


def test_promotion_gate_blocks_on_trace_coverage():
    res = {"truth_overrides": 0, "trace_coverage": 0.5, "packets": []}
    g = promotion_gate(res, behavior_influence_enabled=True)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["trace_coverage"] is False


def test_promotion_gate_blocks_on_mcp_write_attempts():
    res = {"truth_overrides": 0, "trace_coverage": 1.0, "packets": []}
    g = promotion_gate(res, behavior_influence_enabled=True, mcp_write_attempts=1)
    assert g["verdict"] == PROMOTION_NOT_PROMOTED
    assert g["checks"]["mcp_write_attempts_denied"] is False
