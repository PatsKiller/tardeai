"""Lanes F–J hermetic acceptance controls (non-financial)."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.agent_commitment_v1 import (
    count_valid_evaluated,
    evaluate_commitment,
    mint_commitment_from_view,
    validate_commitment_semantics,
)
from scripts.lib.agent_view_v1 import persist_allowed, produce_agent_view_v1
from scripts.lib.prior_calibration_v1 import CalibrationStore, gate_scoring_allowed
from scripts.lib.research_maturity_gaps import (
    build_source_index,
    refuse_obsolete_research_router,
    retention_curation_evidence_bar,
)
from scripts.lib.self_repair_loop_v1 import detect_poller_identity_drift, verify_effect


def test_lane_f_refuses_obsolete_router():
    root = Path(__file__).resolve().parents[1]
    v = refuse_obsolete_research_router(root)
    assert v["canonical_present"] is True
    assert v["obsolete_present"] is False
    assert v["verdict"] == "CANONICAL_ONLY"


def test_lane_f_free_first_index_and_documentation_only_bar():
    idx = build_source_index(
        [
            {"url": "https://paid.example/a", "title": "A", "cost_class": "paid"},
            {"url": "https://free.example/b", "title": "B", "cost_class": "free"},
        ]
    )
    assert idx["sources"][0]["cost_class"] == "free"
    bar = retention_curation_evidence_bar(
        producer=False, consumer=False, schedule=False,
        authoritative_mutation=False, organic_evidence=False,
    )
    assert bar["level"] == "DOCUMENTATION_ONLY"


def test_lane_g_critic_blocks_uncited_and_trade_language():
    bad = produce_agent_view_v1(
        subject="SUBJ", summary="buy shares now", citations=[], confidence=0.9, source_sha="abc"
    )
    assert bad.critic_pass is False
    assert persist_allowed(bad) is False
    good = produce_agent_view_v1(
        subject="SUBJ",
        summary="Evidence suggests quiet tape",
        citations=["src_1"],
        confidence=0.7,
        source_sha="abc",
    )
    assert good.critic_pass is True
    assert good.mbi_behavior == 0
    assert persist_allowed(good) is True


def test_lane_h_semantic_validation_and_outcomes():
    view = produce_agent_view_v1(
        subject="SUBJ", summary="quiet", citations=["s1"], confidence=0.6, source_sha="sha"
    ).to_dict()
    cmt = mint_commitment_from_view(
        view, due_at="2026-09-10T00:00:00Z", horizon="1d", falsifier="price move unexplained"
    ).to_dict()
    ok, errs = validate_commitment_semantics(cmt)
    assert ok, errs
    out = evaluate_commitment(cmt, observation={"confirmed": True})
    assert out["outcome"] == "CONFIRMED"
    gate = count_valid_evaluated([{**cmt, "outcome": out["outcome"]}])
    assert gate["lane_i_gate"] is True


def test_lane_i_scoring_gated_and_refuted_visible():
    assert gate_scoring_allowed(valid_evaluated_commitments=0) is False
    assert gate_scoring_allowed(valid_evaluated_commitments=1) is True
    store = CalibrationStore(cohort="default", source_sha="sha")
    store.add_outcome(commitment_id="c1", confidence=0.7, outcome="REFUTED", lesson_provenance="OUTCOME_DERIVED")
    s = store.summary()
    assert s["refuted"] == 1
    assert s["refuted_hidden"] is False
    assert s["status"] == "insufficient_sample"


def test_lane_j_detects_drift_and_verify_effect():
    before = {"matches_current": False, "mismatch_reason": "cwd_ne_current", "current_source_commit": "845"}
    prop = detect_poller_identity_drift(before)
    assert prop is not None
    assert prop.executable is False
    assert prop.requires_native_grant == "service"
    assert prop.financial_surface_reachable is False
    after = {"matches_current": True}
    v = verify_effect(before=before, after=after)
    assert v["passed"] is True
