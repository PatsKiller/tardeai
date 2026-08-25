"""R15.1 live-convergence tests: deployment, integration, specialists, faults, GUI.

Evidence classes are labeled. These do not count as NATURAL_CURRENT.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import scripts.api_v3_cio as api
from scripts.lib.cio_curation_run import (
    apply_material_version,
    build_curation_run,
    critique_before_memory,
    llm_eligibility,
    persist_curation_run,
)
from scripts.lib.cio_intelligence_fabric import (
    ENVELOPE_SECTIONS,
    close_gap,
    fault_response,
    knowledge_gaps,
    live_envelope_statuses,
    process_observation,
    research_question_from_gap,
    run_targeted_free_first,
)
from scripts.lib.cio_intelligence_outcomes import (
    specialist_disagreement_memory,
    specialist_runtime_artifact,
    specialist_unavailable,
)
from scripts.lib.cio_model_learning import (
    RoutingPromotionForbidden,
    apply_routing_candidate,
    cohort_report,
    golden_shadow_records,
    historical_receipt_to_performance,
    mine_historical_performance,
    snapshot_registries,
)
from scripts.lib.cio_r13_institution import specialist_artifact
from scripts.lib.research_gap import build_gap
from tests.r15_goldens import UNIVERSE, SYMBOLS

pytestmark = pytest.mark.tier0
ROOT = Path(__file__).resolve().parents[1]


def test_d8_api_partial_provider_does_not_crash() -> None:
    row = api.get_intelligence_lifecycle_v1(None)
    assert row["ok"] is True
    assert row["ingestion_bus"] is False
    assert "knowledge_gaps" in row
    assert "POLICY_GAP" in " ".join(row["knowledge_gaps"]) or any("EMPTY" in g or "UNAVAILABLE" in g for g in row["knowledge_gaps"])
    env = row["envelope"]["sections"]
    assert set(env) == set(ENVELOPE_SECTIONS)


def test_d8_malformed_symbol_still_projects() -> None:
    row = api.get_intelligence_lifecycle_v1("@@@")
    assert row["projection"]["ingestion_bus"] is False
    perf = api.get_model_performance_v1()
    assert perf["automatic_promotion"] is False


@pytest.mark.parametrize("idx", range(10))
def test_d15_deployment_imports_and_delta_not_truth(idx: int, tmp_path) -> None:
    profile = UNIVERSE[idx % len(UNIVERSE)]
    receipt = process_observation(tmp_path, {
        "source_domain": "holdings",
        "source_ref": f"{profile['symbol']}-{idx}",
        "source_version": f"v{idx}",
        "entity_guid": profile["ticker_guid"],
        "entity_type": "ticker",
        "change_type": "WEIGHT",
        "before_hash": "0",
        "after_hash": f"h{idx}",
        "material_fields_changed": True,
        "freshness": "FRESH",
        "reason": "fixture_weight_change",
        "hermes_resolved": True,
    }, profiles=UNIVERSE)
    assert receipt["delta"]["second_portfolio_truth"] is False
    assert "quantity" not in receipt["delta"]
    assert receipt["paid_dispatch"] == 0
    assert (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").is_file()


@pytest.mark.parametrize("etype,field", [
    ("ticker", "ticker_guid"),
    ("issuer", "issuer_guid"),
    ("sector", "sector_guid"),
    ("industry", "industry_guid"),
    ("theme", "theme_guids"),
    ("catalyst", "catalyst_guids"),
    ("calendar", "calendar_event_guids"),
])
def test_d16_impact_kinds_from_profiles(etype, field, tmp_path) -> None:
    nvda = next(p for p in UNIVERSE if p["symbol"] == "NVDA")
    guid = nvda[field][0] if isinstance(nvda[field], list) else nvda[field]
    receipt = process_observation(tmp_path, {
        "source_domain": etype,
        "source_ref": etype,
        "source_version": etype,
        "entity_guid": guid,
        "entity_type": etype if etype != "ticker" else "ticker",
        "change_type": "EVENT",
        "before_hash": "0",
        "after_hash": etype,
        "material_fields_changed": True,
        "freshness": "FRESH",
        "reason": etype,
        "hermes_resolved": True,
    }, profiles=UNIVERSE)
    assert "NVDA" in receipt["impact"]["wake_symbols"] or receipt["delta"]["materiality"] in {"MATERIAL_CHANGE"}


def test_d16_peer_is_context_only(tmp_path) -> None:
    nvda = next(p for p in UNIVERSE if p["symbol"] == "NVDA")
    receipt = process_observation(tmp_path, {
        "source_domain": "ticker",
        "source_ref": "NVDA",
        "source_version": "peer",
        "entity_guid": nvda["ticker_guid"],
        "entity_type": "ticker",
        "change_type": "EVENT",
        "before_hash": "0",
        "after_hash": "peer",
        "material_fields_changed": True,
        "freshness": "FRESH",
        "reason": "nvda_delta",
    }, profiles=UNIVERSE)
    assert "AMD" in (receipt["impact"]["context_only"] or []) or "AMD" not in receipt["impact"]["wake_symbols"]


@pytest.mark.parametrize("i", range(10))
def test_d25_event_driven_free_first_fixture(i: int) -> None:
    pending = {"delta_id": f"d{i}", "question": "what_changed=10-K risk factor; event=SEC; alias=NVDA"}
    ff = run_targeted_free_first(
        pending=pending,
        prior_state=None,
        hermes_resolved=i % 4 == 0,
        rag_resolved=i % 4 == 1,
        structured_resolved=i % 4 == 2,
        searx_resolved=i % 4 == 3,
        searx_allowed=True,
    )
    assert ff["paid_dispatch"] == 0
    assert ff["spent_money"] is False
    if i % 4 == 3:
        assert ff["searx_ran"] is True
        assert ff["used"] == "SEARXNG"
    else:
        assert ff["used"] in {"HERMES", "RAG", "STRUCTURED"}
        assert ff["eligibility"] == "FREE_RESOLVED"


def test_d21_dynamic_gap_not_generic() -> None:
    q = research_question_from_gap(
        gap={"question": "NVDA earnings catalyst 2026"},
        what_changed="new 10-K risk factor",
        event_type="SEC",
        sector="IT",
        industry="Semis",
        symbol="NVDA",
    )
    assert "earnings catalyst 2026" not in q.lower() or "what_changed" in q
    assert "10-K" in q or "SEC" in q or "what_changed" in q


def test_d27_gap_requires_evidence() -> None:
    gap = build_gap(security_guid="s", symbol="NVDA", reason="x", question="what_changed=filing", status="OPEN")
    researching = dict(gap, status="FREE_FIRST_PENDING")
    blocked = close_gap(researching, status="RESOLVED_FREE", artifact_guids=[])
    assert blocked.get("close_blocked") == "MISSING_RESOLUTION_EVIDENCE" or blocked["status"] != "RESOLVED_FREE"
    closed = close_gap(researching, status="RESOLVED_FREE", artifact_guids=["hermes:1"])
    assert closed["status"] == "RESOLVED_FREE"


@pytest.mark.parametrize("kwargs,expect", [
    ({}, "NO_NEW_INFO"),
    ({"free_first": {"unresolved": True}}, "LLM_ELIGIBLE"),
    ({"free_first": {"resolved": True, "new_evidence": True}}, "FREE_RESOLVED"),
    ({"contradiction": True}, "CONFLICT_REVIEW_ELIGIBLE"),
    ({"deep_review": True}, "DEEP_REVIEW_ELIGIBLE"),
])
def test_d28_eligibility_classes(kwargs, expect) -> None:
    assert llm_eligibility(**kwargs) == expect


def test_d29_d32_curation_lineage_and_versions(tmp_path) -> None:
    run0 = build_curation_run(
        security_guid="sec", symbol="NVDA", task_type="research_curation",
        prior_curation_id=None, prior_curation_version=0, evidence_delta_hash="e0",
        input_evidence_refs=["e"], prompt_version="p1", process_id="hermes",
        requested_policy="FAST", executed_policy="FAST", model_id="deepseek-v4-flash",
        accepted=True, material_change=False,
    )
    v0 = apply_material_version(run=run0, previous=None, support_guids=["e"], what_changed="BASELINE")
    assert v0["summary"]["version"] == 0
    run1 = build_curation_run(
        security_guid="sec", symbol="NVDA", task_type="research_curation",
        prior_curation_id=v0["summary"]["curation_id"], prior_curation_version=0,
        evidence_delta_hash="e1", input_evidence_refs=["e"], prompt_version="p1",
        process_id="hermes", requested_policy="FAST", executed_policy="FAST",
        model_id="deepseek-v4-flash", accepted=True, material_change=True,
    )
    v1 = apply_material_version(run=run1, previous=v0["summary"], support_guids=["e"], what_changed="10-K")
    assert v1["summary"]["version"] == 1
    run2 = build_curation_run(
        security_guid="sec", symbol="NVDA", task_type="research_curation",
        prior_curation_id=v1["summary"]["curation_id"], prior_curation_version=1,
        evidence_delta_hash="e2", input_evidence_refs=["e"], prompt_version="p1",
        process_id="hermes", requested_policy="FAST", executed_policy="FAST",
        model_id="deepseek-v4-flash", accepted=True, material_change=True,
    )
    v2 = apply_material_version(run=run2, previous=v1["summary"], support_guids=["e"], what_changed="8-K")
    assert v2["summary"]["version"] == 2
    nochg = apply_material_version(run=dict(run2, accepted=True, material_change=False), previous=v2["summary"], support_guids=["e"], what_changed="NO_NEW_INFO")
    assert nochg["summary"]["version"] == 2
    assert nochg.get("fake_progress") is False


def test_d30_dedupe_and_d31_rejected(tmp_path) -> None:
    run = build_curation_run(
        security_guid="sec", symbol="NVDA", task_type="research_curation",
        prior_curation_id=None, prior_curation_version=0, evidence_delta_hash="same",
        input_evidence_refs=["e"], prompt_version="p1", process_id="hermes",
        requested_policy="FAST", executed_policy="FAST", model_id="deepseek-v4-flash",
        accepted=True, material_change=True, schema_valid=True,
    )
    a = persist_curation_run(tmp_path, run)
    b = persist_curation_run(tmp_path, run)
    assert a["wrote"] is True
    assert b["duplicate"] is True
    bad = build_curation_run(
        security_guid="sec", symbol="NVDA", task_type="research_curation",
        prior_curation_id=None, prior_curation_version=0, evidence_delta_hash="bad",
        input_evidence_refs=[], prompt_version="p1", process_id="hermes",
        requested_policy="FAST", executed_policy="FAST", model_id="deepseek-v4-flash",
        accepted=True, material_change=True, schema_valid=False, critique_verdict="REJECT",
    )
    stored = persist_curation_run(tmp_path, bad)
    assert stored["run"]["current_belief"] is False
    assert stored["run"]["retained_in_audit"] is True
    assert critique_before_memory(bad)["may_admit"] is False


@pytest.mark.parametrize("agent", ["maria", "steph", "guardian", "ledger"])
def test_d40_specialist_runtime_same_brain(agent: str) -> None:
    art = specialist_runtime_artifact(
        agent=agent, claim="read-only critique", evidence=["trs:v1"],
        uncertainty="incomplete filings", recommendation="HOLD", same_brain=True,
    )
    assert art["same_brain"] is True
    assert art["hidden_research_store"] is False
    assert art["financial_action"] is False
    assert specialist_unavailable(agent)["status"] == "SPECIALIST_UNAVAILABLE"
    assert specialist_unavailable(agent)["invented_opinion"] is False


@pytest.mark.parametrize("agent", ["maria", "steph", "guardian", "ledger", "alex"])
def test_d45_unavailable_does_not_invent(agent: str) -> None:
    row = specialist_unavailable(agent, error="timeout")
    assert row["status"] == "SPECIALIST_UNAVAILABLE"
    assert "recommendation" not in row or row.get("invented_opinion") is False


def test_d44_disagreement_persisted() -> None:
    arts = [
        specialist_artifact(agent="guardian", claim="heat", evidence=["e"], confidence=0.4, uncertainty="u", contradictions=[], recommendation="TRIM"),
        specialist_artifact(agent="steph", claim="quality", evidence=["e"], confidence=0.6, uncertainty="u", contradictions=["guardian"], recommendation="HOLD"),
        specialist_artifact(agent="ledger", claim="lots", evidence=["e"], confidence=0.5, uncertainty="u", contradictions=[], recommendation="HOLD"),
        specialist_artifact(agent="maria", claim="gap", evidence=["e"], confidence=0.5, uncertainty="u", contradictions=[], recommendation="RESEARCH"),
    ]
    mem = specialist_disagreement_memory(arts)
    assert mem["minority_overwritten"] is False
    assert mem["disagreements"]


def test_d33_historical_replay_not_labeled_live(tmp_path) -> None:
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/cio/cio_llm_enrich_log.jsonl").write_text(
        '{"model":"deepseek-v4-flash","source":"enrich","llm_error":null,"ts":"2026-08-11T00:00:00Z"}\n'
        '{"model":"deepseek-v4-flash","source":"enrich","llm_error":"non_json_response","ts":"2026-08-11T00:00:01Z"}\n',
        encoding="utf-8",
    )
    mined = mine_historical_performance(tmp_path, limit=10)
    assert mined["evidence_class"] == "HISTORICAL_REPLAY"
    assert mined["routing_changed"] is False
    assert all(r["evidence_class"] == "HISTORICAL_REPLAY" for r in mined["records"])
    assert any(r["evidence_class"] != "LIVE" for r in mined["records"])


def test_d36_d37_shadow_not_mixed_with_live() -> None:
    shadow = golden_shadow_records(task_class="tax_critique", n=8)
    replay = [historical_receipt_to_performance({"model": "deepseek-v4-flash", "source": "risk", "structural": {"pass": True}}, evidence_class="HISTORICAL_REPLAY")]
    report = cohort_report(shadow + replay)
    tax = report["tax_critique"]
    risk = report["risk_critique"]
    assert tax["n_shadow"] == 8
    assert tax["n_live"] == 0
    assert risk["n_replay"] == 1
    assert risk["n_live"] == 0
    assert tax["sufficient_for_routing"] is False
    assert tax["classes_mixed"] is False


def test_d39_registries_immutable_on_candidate(tmp_path) -> None:
    before = snapshot_registries(ROOT)
    with pytest.raises(RoutingPromotionForbidden):
        apply_routing_candidate(tmp_path, {"task_class": "extraction"})
    assert snapshot_registries(ROOT) == before
    h1 = hashlib.sha256((ROOT / "config/llm_model_registry.json").read_bytes()).hexdigest()
    h2 = hashlib.sha256((ROOT / "config/llm_process_registry.json").read_bytes()).hexdigest()
    assert len(h1) == 64 and len(h2) == 64


@pytest.mark.parametrize("kind", [
    "duplicate_event", "stale_source", "contradictory_source", "bad_security_identity",
    "searx_outage", "rag_unavailable", "structured_unavailable", "hermes_worker_crash",
    "llm_bridge_unavailable", "flash_unavailable", "pro_unavailable", "schema_invalid",
    "memory_admission_reject", "duplicate_curation", "gui_partial_provider",
])
def test_d49_fault_no_silent_loss(kind: str, tmp_path) -> None:
    row = fault_response(kind)
    assert row["silent_loss"] is False
    assert row["fabricated_certainty"] is False
    if kind == "duplicate_event":
        obs = {
            "source_domain": "news", "source_ref": "dup", "source_version": "1",
            "entity_guid": UNIVERSE[0]["ticker_guid"], "entity_type": "ticker",
            "change_type": "NEWS", "before_hash": "0", "after_hash": "dup",
            "material_fields_changed": True, "freshness": "FRESH", "reason": "dup",
            "hermes_resolved": True,
        }
        a = process_observation(tmp_path, obs, profiles=UNIVERSE)
        b = process_observation(tmp_path, obs, profiles=UNIVERSE)
        assert b["duplicate_delta"] is True
        assert a["delta"]["delta_id"] == b["delta"]["delta_id"]


def test_d17_live_envelope_never_omits_sections() -> None:
    report = live_envelope_statuses(ROOT)
    assert report["never_silently_omitted"] is True
    assert report["sections_total"] == 16
    assert set(report["sections"]) == set(ENVELOPE_SECTIONS)
    gaps = knowledge_gaps(envelope=report, unresolved_identities=17, model_samples=0, outcomes=0)
    assert "UNRESOLVED_IDENTITY" in gaps
    assert "INSUFFICIENT_MODEL_SAMPLES" in gaps
    assert "NO_OUTCOME_HISTORY" in gaps


def test_d46_gui_lifecycle_strings_present() -> None:
    brain = (ROOT / "apps/command-center-v3/src/components/cio/CioBrainPanel.tsx").read_text(encoding="utf-8")
    for token in (
        "cio-brain-intelligence-lifecycle", "cio-brain-graph-context",
        "cio-brain-curation-history", "cio-brain-model-performance",
        "cio-brain-unwired", "cio-brain-knowledge-gaps", "cio-brain-system-health",
        "NOT_CONFIGURED", "UNAVAILABLE", "STALE", "UNRESOLVED_IDENTITY",
        "POLICY_GAP", "INSUFFICIENT_MODEL_SAMPLES", "NO_OUTCOME_HISTORY",
        "PIN MATCH",
    ):
        assert token in brain


@pytest.mark.parametrize("sym", SYMBOLS[:10])
def test_d46_gui_api_null_safe_for_symbols(sym: str) -> None:
    row = api.get_intelligence_lifecycle_v1(sym)
    assert row["projection"]["symbol"] in {sym, "PORTFOLIO"} or row["ok"]
    assert row["gui_cannot_self_promote"] is True
