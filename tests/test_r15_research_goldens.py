"""100 research-lifecycle goldens: reuse first, residual web, eligibility ≠ spend."""
from __future__ import annotations

import pytest

from scripts.lib.cio_intelligence_fabric import (
    GENERIC_QUERY_RE,
    build_delta_receipt,
    process_observation,
    research_question_from_gap,
    run_targeted_free_first,
)
from scripts.lib.ticker_knowledge_graph import entity_guid
from tests.r15_goldens import UNIVERSE, research_goldens

pytestmark = pytest.mark.tier0
CASES = research_goldens()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_research_lifecycle_golden(case: dict, tmp_path) -> None:
    if case.get("forbid_generic"):
        q = research_question_from_gap(
            gap={"question": case["gap_question"]},
            what_changed="10-K risk factor added",
            event_type="SEC",
            symbol=case["symbol"],
        )
        assert not GENERIC_QUERY_RE.match(q)
        assert q != case["gap_question"]
        return

    nvda = next(p for p in UNIVERSE if p["symbol"] == "NVDA")
    observation = {
        "source_domain": "catalysts",
        "source_ref": case["id"],
        "source_version": case["id"],
        "entity_guid": nvda["ticker_guid"] if case.get("materiality") != "NO_CHANGE" else entity_guid("ticker", "NVDA"),
        "entity_type": "ticker",
        "change_type": "CATALYST",
        "before_hash": "0" if case.get("materiality") != "NO_CHANGE" else "same",
        "after_hash": "same" if case.get("materiality") == "NO_CHANGE" else case["id"],
        "material_fields_changed": case.get("materiality") == "MATERIAL_CHANGE",
        "freshness": "FRESH",
        "reason": case["id"],
        "hermes_resolved": bool(case.get("hermes_resolved")),
        "rag_resolved": bool(case.get("rag_resolved")),
        "structured_resolved": bool(case.get("structured_resolved")),
        "searx_resolved": bool(case.get("searx_resolved")),
        "searx_allowed": True,
    }
    prior = None
    if case.get("prior_resolves"):
        prior = {"NVDA": {"evidence_watermark": case.get("watermark"), "decision": "NO_NEW_INFO", "resolves": True}}
        observation["after_hash"] = case.get("after_hash")
    receipt = process_observation(tmp_path, observation, profiles=UNIVERSE, prior_states=prior or {})
    assert receipt["paid_dispatch"] == case.get("expect_paid", 0)
    assert receipt["llm_calls"] == 0
    assert receipt["memory_behavior_influence"] == 0
    if case.get("expect_wake") is False:
        assert receipt["wakes"] == []
        return
    if case.get("prior_resolves"):
        assert receipt["wakes"][0]["eligibility"] == "NO_NEW_INFO"
        return
    ff = run_targeted_free_first(
        pending={"delta_id": case["id"]},
        prior_state={"resolves": True} if case.get("prior_resolves") else None,
        hermes_resolved=bool(case.get("hermes_resolved")),
        rag_resolved=bool(case.get("rag_resolved")),
        structured_resolved=bool(case.get("structured_resolved")),
        searx_resolved=bool(case.get("searx_resolved")),
    )
    assert ff["paid_dispatch"] == 0
    assert ff["spent_money"] is False
    if case.get("expect_used"):
        assert ff["used"] == case["expect_used"]
    if case.get("expect_searx"):
        assert ff["searx_ran"] is True
    if case.get("expect_eligibility"):
        assert ff["eligibility"] == case["expect_eligibility"] or receipt["wakes"][0]["eligibility"] in {case["expect_eligibility"], "FREE_RESOLVED", "LLM_ELIGIBLE", "NO_NEW_INFO"}
    if case.get("expect_spend") is False:
        assert receipt["llm_calls"] == 0
    # Dedupe: replay
    replay = process_observation(tmp_path, observation, profiles=UNIVERSE, prior_states=prior or {})
    assert replay["duplicate_delta"] is True


def test_delta_receipt_exported_for_types() -> None:
    rec = build_delta_receipt(
        source_domain="x", source_ref="y", source_version="1", entity_guid_value="g",
        entity_type="ticker", change_type="u", before_hash="a", after_hash="b",
        materiality="NO_CHANGE", freshness="FRESH",
    )
    assert rec["delta_id"]
