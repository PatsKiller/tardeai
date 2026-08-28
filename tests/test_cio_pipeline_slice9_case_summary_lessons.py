"""Slice 9: CASE_SUMMARY as supporting lesson context. Cap REVIEW_READY. MBI=0."""
from __future__ import annotations

from scripts.lib.agent_memory_governance import MEMORY_TYPE_CASE_SUMMARY, STATUS_ACTIVE
from scripts.lib.cio_institutional_learning import promotion_advance
from scripts.lib.outcome_to_lesson import candidates_from_case_summaries


def test_case_summary_is_support_not_policy():
    recs = [
        {
            "memory_type": MEMORY_TYPE_CASE_SUMMARY,
            "status": STATUS_ACTIVE,
            "memory_id": "mem_a",
            "subject": "research_case:SCHD",
            "symbols": ["SCHD"],
            "plan_ids": ["plan_a"],
            "source_refs": ["plan_a", "res_a", "rr_a"],
            "content": "Hermes VALID. Advisory only.",
        },
        {
            "memory_type": MEMORY_TYPE_CASE_SUMMARY,
            "status": STATUS_ACTIVE,
            "memory_id": "mem_a2",
            "subject": "research_case:SCHD",
            "symbols": ["SCHD"],
            "plan_ids": ["plan_a"],
            "source_refs": ["plan_a", "res_a", "rr_a"],
            "content": "duplicate join",
        },
    ]
    cands = candidates_from_case_summaries(recs)
    assert len(cands) == 1
    c = cands[0]
    assert c["role"] == "SUPPORTING_CONTEXT"
    assert c["status"] == "PROVISIONAL"
    assert c["promotion_stage"] == "REVIEW_READY"
    assert c["cannot_become_policy"] is True
    assert c["policy_effect"] is False
    assert c["memory_behavior_influence"] in {0, "0"}
    assert c["plan_id"] == "plan_a"
    assert c["hermes_result_id"] == "res_a"
    assert "mem_a" in c["supporting_case_summary_ids"]
    adv = promotion_advance("REVIEW_READY", "OPERATOR_APPROVED", operator_authorized=False)
    assert adv["ok"] is False
    assert adv.get("max_unattended") == "REVIEW_READY"


def test_research_reference_not_used():
    cands = candidates_from_case_summaries([{
        "memory_type": "RESEARCH_REFERENCE",
        "status": "CANDIDATE",
        "memory_id": "mem_rr",
        "subject": "research observation SCHD",
        "symbols": ["SCHD"],
        "plan_ids": ["plan_x"],
        "source_refs": ["plan_x", "res_x", "rr_x"],
    }])
    assert cands == []
