"""Governed advisory learning influence — no execution, no MEMORY_BEHAVIOR_INFLUENCE reuse."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.advisory_influence.comparator import compare_run, metrics
from scripts.lib.advisory_influence.gates import current_gates, fs_receipt_eligible, lesson_eligible
from scripts.lib.advisory_influence.restrict import should_restrict


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    return tmp_path


def _write_ratified(root: Path) -> None:
    rec = {
        "id": "les_r1", "status": "ratified", "title": "trim fire line",
        "symbols": ["SCHD"], "source": "iris", "applications": 5, "hit_rate": 0.8,
        "evidence_refs": ["case_1"],
    }
    (root / "data" / "runtime" / "advisory_kb_lessons.jsonl").write_text(json.dumps(rec) + "\n")


def test_candidate_never_influences(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "SHADOW")
    (root / "data" / "runtime" / "advisory_kb_lesson_candidates.jsonl").write_text(json.dumps({
        "id": "cand1", "status": "candidate", "title": "noise",
    }) + "\n")
    out = compare_run({"verdict": "HOLD", "conviction": 0.4}, root=root)
    assert out["enhanced"]["lessons"] == []
    assert out["executed"] is False


def test_ratified_lesson_shadow_only(root: Path, monkeypatch: pytest.MonkeyPatch):
    _write_ratified(root)
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    out = compare_run({"verdict": "HOLD", "conviction": 0.4, "canonical_action": "HOLD"}, root=root)
    assert out["gates"]["lesson_mode"] == "SHADOW"
    assert out["enhanced"]["lessons"][0]["lesson_id"] == "les_r1"
    assert out["enhanced"]["verdict"] == out["baseline"]["verdict"] == "HOLD"
    assert out["enhanced"]["primary"] is False
    assert out["gates"]["memory_behavior_influence_untouched"] is True


def test_canonical_conflict_suppresses_lesson(root: Path, monkeypatch: pytest.MonkeyPatch):
    _write_ratified(root)
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "SHADOW")
    out = compare_run({
        "verdict": "HOLD", "conviction": 0.4, "canonical_action": "HOLD",
        "lesson_conflicts_canonical": True,
    }, root=root)
    assert "lesson_conflicts_canonical_truth" in out["conflicts"]
    assert any("contradicted by current canonical truth" in x for x in out["enhanced"]["rationale"])


def test_stale_fs_does_not_influence(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "SHADOW")
    rec = {"request_id": "r1", "status": "STALE", "provider": "sec_edgar"}
    assert fs_receipt_eligible(rec) is False
    out = compare_run({"verdict": "HOLD", "conviction": 0.2}, root=root, fs_receipts=[rec])
    assert out["enhanced"]["fs_receipts"] == []


def test_ok_fs_labeled(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "SHADOW")
    rec = {
        "request_id": "r2", "status": "OK", "fs_provider": "sec_edgar",
        "fs_capability": "sec.get_company_facts", "fact_count": 3, "estimate_count": 1,
        "source_asof": "2026-08-18T00:00:00+00:00",
        "source_provenance": {"source_type": "PRIMARY_REGULATORY"},
        "quality_summary": "HIGH",
    }
    assert fs_receipt_eligible(rec) is True
    out = compare_run({"verdict": "HOLD", "conviction": 0.2}, root=root, fs_receipts=[rec])
    assert out["enhanced"]["fs_receipts"][0]["fact_count"] == 3
    assert out["enhanced"]["fs_receipts"][0]["estimate_count"] == 1


def test_baseline_deterministic(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "OFF")
    a = compare_run({"verdict": "TRIM", "conviction": 0.5}, root=root)
    b = compare_run({"verdict": "TRIM", "conviction": 0.5}, root=root)
    assert a["baseline"] == b["baseline"]
    assert a["input_digest"] == b["input_digest"]


def test_no_execution_or_broker_delta(root: Path, monkeypatch: pytest.MonkeyPatch):
    _write_ratified(root)
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "CANARY")
    out = compare_run({"verdict": "HOLD", "conviction": 0.3, "canonical_action": "HOLD"}, root=root)
    assert out["executed"] is False
    assert out["financial_action"] is False
    assert out["enhanced"]["verdict"] == "HOLD"
    assert should_restrict(metrics([out])) is False


def test_off_mode_default():
    g = current_gates({})
    assert g["lesson_mode"] == "OFF"
    assert g["financial_senses_mode"] == "OFF"
    assert lesson_eligible("CANDIDATE") is False
    assert lesson_eligible("RATIFIED_CONTEXT") is True
