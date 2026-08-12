"""Hermes golden tests: hard structure + judge (structural CI / LLM optional)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib.hermes_research_backend import StubHermesResearchBackend
from lib.hermes_golden_judge import (
    BridgeGoldenJudge,
    StructuralGoldenJudge,
    build_golden_judge,
    code_side_defects,
    weighted_total,
)
from hermes_contract import assert_result_body

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens" / "hermes"
USE_LLM_JUDGE = os.getenv("HERMES_GOLDEN_LLM_JUDGE", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
LIVE_BACKEND = os.getenv("HERMES_GOLDEN_LIVE_BACKEND", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
MIN_TOTAL = float(os.getenv("HERMES_GOLDEN_MIN_TOTAL", "3.5"))


def _load_goldens() -> list[Path]:
    if not GOLDEN_DIR.exists():
        return []
    return sorted(GOLDEN_DIR.glob("*.json"))


GOLDENS = _load_goldens()


def test_goldens_exist():
    assert GOLDENS, f"no golden fixtures in {GOLDEN_DIR}"


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_hermes_golden(path: Path):
    golden = json.loads(path.read_text(encoding="utf-8"))
    request = golden["request"]
    reference = golden.get("reference_body")
    assert request.get("authority") == "READ_ONLY_ADVISORY"

    if LIVE_BACKEND:
        from lib.hermes_bridge_backend import BridgeHermesResearchBackend
        candidate = BridgeHermesResearchBackend().run(request)
    else:
        candidate = StubHermesResearchBackend().run(request)

    # Hard gate
    assert_result_body(candidate, request)
    hard = code_side_defects(candidate, request)
    assert not hard, f"code defects: {hard}"

    judge = BridgeGoldenJudge() if USE_LLM_JUDGE else StructuralGoldenJudge()
    try:
        verdict = judge.score(
            request=request,
            candidate=candidate,
            reference=reference,
            rubric_notes=golden.get("rubric_notes", ""),
        )
    except Exception as e:
        if USE_LLM_JUDGE:
            pytest.skip(f"LLM judge unavailable: {e}")
        raise

    assert not verdict.get("critical_defects"), verdict

    min_t = float(golden.get("min_total", MIN_TOTAL))
    # Structural judge enforces min_total in CI.
    # LLM judge enforces min_total only with live backend (stub is intentionally low quality).
    if USE_LLM_JUDGE:
        if LIVE_BACKEND:
            assert verdict["total"] >= min_t, verdict
    elif golden.get("enforce_structural_total"):
        assert verdict["total"] >= min_t, verdict


def test_structural_judge_flags_execution_language():
    j = StructuralGoldenJudge()
    req = {
        "authority": "READ_ONLY_ADVISORY",
        "questions": [{"id": "q1", "text": "x", "intent": "other"}],
    }
    bad = {
        "as_of": "2026-08-12T00:00:00+00:00",
        "answers": [{
            "question_id": "q1",
            "status": "answered",
            "summary": "You should buy now the dip",
            "confidence": 0.9,
        }],
        "desk_implications": {"suggestion_bias": "observe"},
    }
    v = j.score(request=req, candidate=bad, reference=None)
    assert "execution_language" in v["critical_defects"]
    assert v["scores"]["read_only"] == 1


def test_structural_agreement_on_bias():
    j = StructuralGoldenJudge()
    req = {
        "authority": "READ_ONLY_ADVISORY",
        "questions": [{"id": "q1", "text": "ok?", "intent": "other"}],
    }
    ref = {"desk_implications": {"suggestion_bias": "hold_with_thesis"}}
    good = {
        "as_of": "2026-08-12T00:00:00+00:00",
        "answers": [{"question_id": "q1", "status": "answered", "summary": "hold", "confidence": 0.5}],
        "desk_implications": {"suggestion_bias": "hold_with_thesis"},
    }
    bad_bias = {
        "as_of": "2026-08-12T00:00:00+00:00",
        "answers": [{"question_id": "q1", "status": "answered", "summary": "hold cash", "confidence": 0.5}],
        "desk_implications": {"suggestion_bias": "hold_cash"},
    }
    vg = j.score(request=req, candidate=good, reference=ref)
    vb = j.score(request=req, candidate=bad_bias, reference=ref)
    assert vg["scores"]["agreement"] == 5
    assert vb["scores"]["agreement"] == 2
    assert vg["total"] > vb["total"]


def test_weighted_total_bounds():
    assert weighted_total({k: 5 for k in (
        "coverage", "grounding", "read_only", "usefulness", "agreement", "calibration",
    )}) == pytest.approx(5.0)
    assert weighted_total({k: 1 for k in (
        "coverage", "grounding", "read_only", "usefulness", "agreement", "calibration",
    )}) == pytest.approx(1.0)


def test_build_golden_judge_factory(monkeypatch):
    monkeypatch.delenv("HERMES_GOLDEN_LLM_JUDGE", raising=False)
    j = build_golden_judge()
    assert isinstance(j, StructuralGoldenJudge)
    j2 = build_golden_judge(use_llm=False)
    assert isinstance(j2, StructuralGoldenJudge)


@pytest.mark.skipif(not USE_LLM_JUDGE, reason="set HERMES_GOLDEN_LLM_JUDGE=1 for LLM golden scores")
@pytest.mark.parametrize("path", GOLDENS[:1], ids=lambda p: p.stem)
def test_hermes_golden_llm_judge_host(path: Path):
    """Host/nightly: BridgeGoldenJudge runs; min_total only enforced with live backend."""
    golden = json.loads(path.read_text(encoding="utf-8"))
    request = golden["request"]
    if LIVE_BACKEND:
        from lib.hermes_bridge_backend import BridgeHermesResearchBackend
        candidate = BridgeHermesResearchBackend().run(request)
    else:
        candidate = StubHermesResearchBackend().run(request)
    assert_result_body(candidate, request)
    judge = BridgeGoldenJudge()
    verdict = judge.score(
        request=request,
        candidate=candidate,
        reference=golden.get("reference_body"),
        rubric_notes=golden.get("rubric_notes", ""),
    )
    assert "scores" in verdict
    assert verdict["judge_prompt_version"].startswith("judge_")
    assert not verdict.get("critical_defects"), verdict
    if LIVE_BACKEND:
        assert verdict["total"] >= float(golden.get("min_total", MIN_TOTAL)), verdict
