from __future__ import annotations

from scripts.lib.noc_golden_loop import run_noc_golden_loop


def test_noc_golden_loop_eight_stages_and_no_new_info_replay(tmp_path):
    proof = run_noc_golden_loop(tmp_path)
    stages = proof["stages"]
    replay = proof["replay"]

    research = stages["research"]
    assert research["status"] == "CURRENT"
    assert research["recommendation"] and research["dissent"]
    assert research["evidence"] and research["contradictory_evidence"]
    assert research["raw_response_provenance"]["sha256"]

    first = stages["automatic_reconciliation"]
    assert first["version_published"] is True
    assert first["new_version"] == "symbol_noc@v2"
    assert first["delta"]["classification"] == "STRENGTHENS"
    assert first["delta"]["authority"] == "READ_ONLY_ADVISORY"

    full_summary = research["recommendation"]
    assert stages["advisory"]["thesis_version"] == "symbol_noc@v2"
    assert stages["advisory"]["summary"] == full_summary
    assert stages["cio"]["current_symbol_thesis"]["version"] == "symbol_noc@v2"
    assert stages["cio"]["current_symbol_thesis"]["summary"] == full_summary
    assert stages["symbol_card"]["core_thesis"] == full_summary
    assert stages["symbol_card"]["cio_action"]["decision_id"] == "dec_noc_golden_v2"

    gate = stages["decision_gate"]
    assert gate["delta_id"] == first["delta"]["delta_id"]
    assert gate["effective_action"] == "READY"
    assert gate["positive_delta_created_promotion"] is False
    assert stages["decision_emit"]["emitted"] == 1

    feedback = stages["feedback"]
    assert feedback["linkage_complete"] is True
    assert feedback["decision_id"] == "dec_noc_golden_v2"
    assert feedback["thesis_version"] == "symbol_noc@v2"
    assert feedback["behavior_authority"] is False

    next_prompt = stages["next_prompt"]
    assert next_prompt["standing_thesis"]["version"] == "symbol_noc@v2"
    assert next_prompt["previous_research_delta"]["delta_id"] == first["delta"]["delta_id"]
    assert next_prompt["previous_research_conclusion"]["research_id"] == "research_noc_golden_1"
    assert next_prompt["unresolved_research_gaps"] == ["next-quarter cash conversion"]
    assert next_prompt["deterministic_current_data"]["price"] == 590.0
    assert next_prompt["rag"]["supporting"] and next_prompt["rag"]["contradictory"]
    assert next_prompt["operator_feedback"][0]["decision_id"] == "dec_noc_golden_v2"
    assert next_prompt["memory_context"]["authority"] == "NON_AUTHORITATIVE_CONTEXT"
    assert next_prompt["ratified_lessons"] and next_prompt["financial_senses_receipts"]
    assert next_prompt["counter_evidence"]

    assert replay["delta_classification"] == "NO_NEW_INFO"
    assert replay["version_published"] is False
    assert replay["final_thesis_version"] == "symbol_noc@v2"
    assert replay["thesis_change_cards"] == 1
    assert replay["decision_traces"] == 1
    assert replay["second_decision_emit"]["emitted"] == 0
    assert replay["second_decision_emit"]["skipped_unchanged"] == 1
    assert replay["research_requests_created"] == 0
    assert replay["notifications_sent"] == 0
    assert replay["telegram_messages_sent"] == 0
    assert proof["financial_writes"] == 0
    assert proof["memory_behavior_influence"] == 0
    assert proof["live_proven"] is False
