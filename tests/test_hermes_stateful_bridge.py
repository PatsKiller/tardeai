import json

from scripts.lib.hermes_bridge_backend import BridgeHermesResearchBackend
from scripts.lib.hermes_research_schema import stamp_result


def test_bridge_prompt_receives_exact_stateful_context():
    backend = BridgeHermesResearchBackend(model="cloud-test")
    context = {
        "schema": "ResearchPromptContext@v1",
        "standing_thesis": {"version": "symbol_noc@v7", "summary": "standing NOC thesis"},
        "previous_research_delta": {"classification": "WEAKENS"},
        "unresolved_research_gaps": ["cash conversion"],
        "deterministic_changes_since_prior_review": [{"field": "price", "before": 580, "after": 590}],
        "rag": {"supporting": [{"evidence_id": "support_1"}], "contradictory": [{"evidence_id": "counter_1"}]},
        "operator_feedback": [{"intent": "DEFER"}],
        "memory_context": {"authority": "NON_AUTHORITATIVE_CONTEXT", "memory_behavior_influence": "0"},
        "prompt_context_hash": "hash_1",
        "authority": "READ_ONLY_ADVISORY",
    }
    request = {
        "authority": "READ_ONLY_ADVISORY",
        "symbol": "NOC",
        "thesis_version": "symbol_noc@v7",
        "questions": [{"question_id": "q1", "text": "What changed?", "intent": "thesis_check"}],
        "prompt_context": context,
    }
    messages = backend._build_messages(request, [{"id": "q1", "text": "What changed?", "intent": "thesis_check"}])
    payload = json.loads(messages[1]["content"].split("Request:\n", 1)[1])
    assert payload["prompt_context"] == context
    assert payload["prompt_context"]["rag"]["supporting"][0]["evidence_id"] == "support_1"
    assert payload["prompt_context"]["rag"]["contradictory"][0]["evidence_id"] == "counter_1"


def test_worker_stamp_preserves_delta_contract_without_chain_of_thought():
    request = {
        "research_id": "res_noc",
        "plan_id": "plan_noc",
        "symbol": "NOC",
        "thesis_version": "symbol_noc@v7",
    }
    body = {
        "as_of": "2026-08-22T20:00:00+00:00",
        "summary": "NOC research summary",
        "recommendation": "NOC living thesis",
        "classification": "WEAKENS",
        "confidence": 0.7,
        "evidence": [{"evidence_id": "ev1"}],
        "contradictory_evidence": [{"evidence_id": "ev2"}],
        "what_changed": ["margin evidence"],
        "research_gaps_remaining": ["cash conversion"],
        "source_refs": ["sec:noc:10-q"],
        "provider": "governed_bridge",
        "model": "cloud-test",
        "raw_chain_of_thought": "must never survive",
    }
    result = stamp_result(request, body, worker_id="worker-1", result_id="rr_noc")
    assert result["classification"] == "WEAKENS"
    assert result["recommendation"] == "NOC living thesis"
    assert result["source_refs"] == ["sec:noc:10-q"]
    assert "raw_chain_of_thought" not in result
