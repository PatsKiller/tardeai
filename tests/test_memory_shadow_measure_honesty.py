"""Phase B.1 — zero v1 payloads must not look like decision evidence."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.agent_decision_payload import PAYLOAD_SCHEMA, count_decision_payloads
from scripts.lib.agent_memory_shadow_measure import load_decision_payloads, run_measure


def _trace(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_count_excludes_synthesized_from_promotion_tally(tmp_path: Path):
    p = tmp_path / "agent_run_traces.jsonl"
    _trace(p, [
        {"decision": {"schema": PAYLOAD_SCHEMA, "decision_origin": "DETERMINISTIC_RANK"}},
        {"decision": {"schema": PAYLOAD_SCHEMA, "decision_origin": "SYNTHESIZED"}},
        {"decision": {"current_action": None}},
    ])
    stats = count_decision_payloads(p)
    assert stats["with_decision_payload_v1"] == 2
    assert stats["synthesized"] == 1
    assert stats["with_decision_payload_v1_non_synth"] == 1
    loaded = load_decision_payloads(p)
    assert len(loaded) == 1
    assert loaded[0]["decision_origin"] == "DETERMINISTIC_RANK"


def test_run_measure_zero_v1_forces_unavailable(tmp_path, monkeypatch):
    traces = tmp_path / "agent_run_traces.jsonl"
    wakes = tmp_path / "cio_wake_traces.jsonl"
    _trace(traces, [{"decision": {"current_action": None, "decision_id": None}}])
    _trace(wakes, [{"wake_id": "w1", "trace_id": "t1"}])

    captured: dict = {}

    def fake_shadow(*_a, **kw):
        captured["evaluator"] = kw.get("decision_evaluator")
        return {
            "wakes": 1,
            "trace_coverage": 1.0,
            "packets": [],
            "decision_payloads_available": True,  # would-be lie from HOLD fallback
            "decision_comparisons_completed": True,
            "dual_path_executed": True,
            "memory_attributable_action_flips": 0,
            "evaluation_failures": 0,
        }

    monkeypatch.setattr(
        "scripts.lib.agent_memory_shadow_measure.shadow_compare_wakes",
        fake_shadow,
    )
    monkeypatch.setattr(
        "scripts.lib.agent_memory_shadow_measure.get_memory_provider",
        lambda *_a, **_k: None,
        raising=False,
    )

    report = run_measure(
        wake_path=wakes,
        trace_path=traces,
        out_path=tmp_path / "out.json",
        root=tmp_path,
    )
    assert captured.get("evaluator") is None
    assert report["window"]["payload_v1_count"] == 0
    assert report["metrics"]["decision_payload_v1_count"] == 0
    assert report["shadow"]["decision_payloads_available"] is False
    assert report["shadow"]["dual_path_executed"] is False
