"""Phase 2 — memory shadow measure harness tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.agent_decision_payload import (  # noqa: E402
    build_decision_payload,
    emit_decision_payload,
)
from scripts.lib.agent_feature_flags import load_feature_flags  # noqa: E402
from scripts.lib.agent_memory_shadow_measure import (  # noqa: E402
    compute_phase2_metrics,
    make_decision_evaluator,
    run_measure,
)
from scripts.lib.agent_shadow_acceptance import PROMOTION_NOT_PROMOTED  # noqa: E402


def _flags(**kw):
    f = load_feature_flags({})
    f.update(kw)
    return f


def test_evaluator_returns_distinct_objects():
    pl = build_decision_payload(
        decision_id="dec_1",
        wake_id="wake_1",
        symbol="UBER",
        current_action="WAIT",
    )
    ev = make_decision_evaluator({"wake_1": pl})
    wake = {"wake_id": "wake_1", "trace_id": "tr_1"}
    ctx = {"episodic_memory": {"memory_ids": ["mem_a"]}}
    a = ev(wake, ctx, "baseline")
    b = ev(wake, ctx, "augmented")
    assert a is not b
    assert a["current_action"] == "WAIT"
    assert a["memory_ids_used"] == []
    assert b["memory_ids_used"] == ["mem_a"]


def test_run_measure_influence_stays_off_and_not_promoted(tmp_path, monkeypatch):
    # Seed wake + payload
    wake_p = tmp_path / "wakes.jsonl"
    trace_p = tmp_path / "traces.jsonl"
    out_p = tmp_path / "measure.json"
    wake = {
        "wake_id": "wake_m1",
        "trace_id": "tr_m1",
        "phase": "close",
        "ts": "2026-08-21T12:00:00+00:00",
    }
    wake_p.write_text(json.dumps(wake) + "\n", encoding="utf-8")
    pl = build_decision_payload(
        decision_id="dec_m1",
        wake_id="wake_m1",
        trace_id="tr_m1",
        symbol="UBER",
        current_action="HOLD",
    )
    emit_decision_payload(
        pl,
        flags=_flags(AGENT_DECISION_PAYLOAD=1),
        path=trace_p,
    )
    monkeypatch.setenv("MEMORY_PROVIDER", "null")
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("AGENT_DECISION_PAYLOAD", "1")
    report = run_measure(
        wake_path=wake_p,
        trace_path=trace_p,
        out_path=out_p,
        root=tmp_path,
    )
    assert report["metrics"]["behavior_influence_active"] is False
    assert report["promotion_gate"]["verdict"] == PROMOTION_NOT_PROMOTED
    assert report["ttl_policy"]["decision"] == "KEEP_CURRENT_TTLS"
    assert out_p.exists()
    assert report["metrics"]["decision_payload_v1_count"] >= 1


def test_compute_metrics_unavailable_when_no_wakes():
    m = compute_phase2_metrics(
        {"wakes": 0, "packets": []},
        payload_stats={"rows": 0, "with_decision_payload_v1": 0, "coverage": 0.0},
        flags=_flags(),
    )
    assert m["memory_retrieval_rate"] == "UNAVAILABLE"
    assert m["truth_override_attempts"] == 0
