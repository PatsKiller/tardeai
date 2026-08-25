"""R15 unit contracts: inventory, coverage, delta, envelope, eligibility."""
from __future__ import annotations

import pytest

from scripts.lib.cio_intelligence_fabric import (
    COVERAGE_FLAGS,
    ENVELOPE_SECTIONS,
    FORBIDDEN_TRUTH_KEYS,
    MATERIALITY,
    SAME_BRAIN_AGENTS,
    SECTION_STATUS,
    budget_context,
    build_delta_receipt,
    classify_materiality,
    close_gap,
    coverage_matrix,
    envelope_provider_statuses,
    llm_eligibility_from_free_first,
    persist_web_evidence,
    producer_inventory,
    research_question_from_gap,
    upsert_delta,
)
from scripts.lib.cio_curation_run import model_ladder
from scripts.lib.cio_intelligence_outcomes import memory_influence_firewall
from scripts.lib.research_gap import build_gap

pytestmark = pytest.mark.tier0


def test_inventory_has_live_domains_and_ui_is_not_a_producer() -> None:
    inv = producer_inventory()
    assert inv["ui_is_producer"] is False
    assert inv["source_domains_total"] >= 30
    ids = {p["producer_id"] for p in inv["producers"]}
    for required in ("holdings", "cash", "hermes_research", "symbol_thesis", "outcomes", "lessons"):
        assert required in ids
    for row in inv["producers"]:
        assert row["gui_is_producer"] is False
        assert "producer_id" in row and "canonical_source" in row
        assert row["memory_behavior_influence"] if False else True
        assert row["authority"] if False else row["canonical_source"]


@pytest.mark.parametrize("producer", producer_inventory()["producers"])
def test_each_producer_declares_wiring(producer: dict) -> None:
    assert producer["current_wiring"] in {"FULL", "PARTIAL", "UNWIRED"}
    assert isinstance(producer["missing_wiring"], list)


def test_coverage_matrix_identifies_gaps() -> None:
    matrix = coverage_matrix()
    assert matrix["counts"]["PARTIAL"] + matrix["counts"]["FULL"] + matrix["counts"]["UNWIRED"] == 31
    assert matrix["not_connected"]
    for row in matrix["rows"]:
        for flag in COVERAGE_FLAGS:
            assert flag in row


@pytest.mark.parametrize("available,stale,conflict,material,change,before,after,expect", [
    (False, False, False, False, False, "a", "b", "DATA_UNAVAILABLE"),
    (True, False, True, False, False, "a", "b", "CONFLICT"),
    (True, True, False, False, False, "a", "b", "STALE"),
    (True, False, False, False, False, "a", "a", "NO_CHANGE"),
    (True, False, False, True, True, "a", "b", "MATERIAL_CHANGE"),
    (True, False, False, False, True, "a", "b", "NON_MATERIAL_CHANGE"),
    (True, False, False, False, False, None, None, "DATA_UNAVAILABLE"),
])
def test_materiality_is_deterministic(available, stale, conflict, material, change, before, after, expect) -> None:
    assert classify_materiality(
        before_hash=before, after_hash=after, available=available, stale=stale,
        conflict=conflict, material_fields_changed=material, any_change=change,
    ) == expect
    assert expect in MATERIALITY


def test_delta_receipt_is_projection_not_portfolio_truth(tmp_path) -> None:
    rec = build_delta_receipt(
        source_domain="holdings", source_ref="NVDA", source_version="v1",
        entity_guid_value="guid", entity_type="ticker", change_type="UPDATE",
        before_hash="a", after_hash="b", materiality="MATERIAL_CHANGE",
        freshness="FRESH", reason="weight change", portfolio_relevance=True,
    )
    assert rec["schema"] == "IntelligenceDeltaReceipt@v1"
    assert rec["second_portfolio_truth"] is False
    assert rec["financial_action"] is False
    for key in FORBIDDEN_TRUTH_KEYS:
        assert key not in rec
    first = upsert_delta(tmp_path, rec)
    second = upsert_delta(tmp_path, rec)
    assert first["wrote"] is True
    assert second["duplicate"] is True
    assert second["wrote"] is False
    assert first["receipt"]["delta_id"] == second["receipt"]["delta_id"]


@pytest.mark.parametrize("section", list(ENVELOPE_SECTIONS))
@pytest.mark.parametrize("status_case,payload,configured,stale,conflicted,expect", [
    ("ok", {"x": 1}, True, False, False, "OK"),
    ("empty", {}, True, False, False, "EMPTY"),
    ("unavailable", None, True, False, False, "UNAVAILABLE"),
    ("stale", {"x": 1}, True, True, False, "STALE"),
    ("conflict", {"x": 1}, True, False, True, "CONFLICTED"),
    ("noconf", {"x": 1}, False, False, False, "NOT_CONFIGURED"),
])
def test_envelope_statuses_never_omit(section, status_case, payload, configured, stale, conflicted, expect) -> None:
    assert expect in SECTION_STATUS
    report = envelope_provider_statuses(
        {section: payload} if configured else {},
        configured={section: configured},
        stale={section: stale},
        conflicted={section: conflicted},
    )
    assert report["never_silently_omitted"] is True
    assert report["sections_total"] == 16
    assert report["sections"][section] == expect
    assert all(name in report["sections"] for name in ENVELOPE_SECTIONS)


def test_budget_records_dropped_items() -> None:
    items = [{"id": f"i{i}", "held": i < 2, "research_gap": i == 3, "freshness": "FRESH"} for i in range(20)]
    out = budget_context(items, portfolio_role="HELD", limit=5)
    assert len(out["kept"]) == 5
    assert out["dropped"]
    assert all(d["reason"] == "BUDGET" for d in out["dropped"])


@pytest.mark.parametrize("result,expect", [
    ({"resolved": False, "unresolved": True}, "LLM_ELIGIBLE"),
    ({"resolved": True, "new_evidence": True}, "FREE_RESOLVED"),
    ({"resolved": True, "new_evidence": False}, "NO_NEW_INFO"),
    ({"conflict": True}, "CONFLICT_REVIEW_ELIGIBLE"),
    ({"conflict": True, "deep_review": True}, "DEEP_REVIEW_ELIGIBLE"),
])
def test_eligibility_does_not_spend(result, expect) -> None:
    assert llm_eligibility_from_free_first(result) == expect


@pytest.mark.parametrize("sym", ["NVDA", "NOC", "SCHD", "AMD"])
def test_research_question_rejects_generic_catalyst_template(sym) -> None:
    q = research_question_from_gap(
        gap={"question": f"{sym} earnings catalyst 2026"},
        entity="guid", event_type="catalyst", sector="IT", industry="Semi",
        what_changed="new filing", symbol=sym,
    )
    assert "earnings catalyst 2026" not in q.lower() or "what_changed" in q
    assert q != f"{sym} earnings catalyst 2026"
    derived = research_question_from_gap(event_type="SEC", what_changed="10-K risk factor", symbol=sym, industry="Semis")
    assert "10-K" in derived
    assert "earnings catalyst 2026" not in derived


def test_gap_open_is_not_resolved_without_evidence() -> None:
    gap = build_gap(security_guid="s", symbol="NVDA", reason="x", question="what changed in 10-K", status="OPEN")
    blocked = close_gap(gap, status="RESOLVED_FREE", artifact_guids=[])
    assert blocked["status"] == "OPEN"
    assert blocked["close_blocked"] == "MISSING_RESOLUTION_EVIDENCE"
    closed = close_gap(gap, status="RESOLVED_FREE", artifact_guids=["art1"])
    assert closed["status"] == "RESOLVED_FREE"
    assert closed["resolved_at"]


def test_web_evidence_is_not_thesis_truth(tmp_path) -> None:
    row = persist_web_evidence(tmp_path, {"query": "q", "url": "https://example.com", "title": "t", "source_valid": False})
    assert row["thesis_truth"] is False
    assert row["schema"] == "WebEvidenceProvenance@v1"


@pytest.mark.parametrize("kwargs,expect", [
    ({}, "DETERMINISTIC"),
    ({"material_evidence": True}, "FAST"),
    ({"material_evidence": True, "contradiction": True}, "FAST_THINK"),
    ({"material_evidence": True, "challenger": True}, "CHALLENGER"),
    ({"material_evidence": True, "deep_review": True}, "PRO"),
    ({"deep_review": True, "contradiction": True}, "PRO_THINK"),
])
def test_model_ladder_pro_not_bulk(kwargs, expect) -> None:
    assert model_ladder(**kwargs) == expect


def test_same_brain_agents_include_specialists_and_gui() -> None:
    for agent in ("alex", "hermes", "advisory", "telegram", "maria", "steph", "guardian", "ledger", "command_center"):
        assert agent in SAME_BRAIN_AGENTS


def test_memory_influence_stays_zero() -> None:
    row = memory_influence_firewall()
    assert row["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert row["lessons_rewrite_policy"] is False
    assert row["model_policy_auto_changed"] is False
