from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.research_prompt_context import build_research_prompt_context
from scripts.lib.research_thesis_delta import accept_research_result, build_research_thesis_delta


def _fields(_symbol: str, **_kwargs):
    return {
        "symbol_thesis_id": "symbol_noc",
        "symbol_thesis_version": "symbol_noc@v7",
        "thesis_state": "CURRENT",
        "thesis_stance": "HOLD",
        "thesis_summary": "NOC is held for defense exposure while program execution remains intact.",
        "last_reviewed": "2026-08-20T12:00:00+00:00",
        "thesis_age_days": 2,
        "fresh": True,
        "portfolio_role": "DEFENSIVE_GROWTH",
        "memberships": ["HELD", "T0"],
        "evidence_for": ["rag_old_support"],
        "counter_evidence": ["rag_old_counter"],
        "invalidation_conditions": ["program cancellations accelerate"],
        "research_gaps": ["quantify B-21 margin progression"],
    }


def _prompt_context(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.setattr("scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol", _fields)
    kwargs = {
        "symbol": "NOC",
        "question": "What changed in the NOC thesis?",
        "root": tmp_path,
        "rag_catalog": {
            "supporting": [{"evidence_id": "rag_new_support", "text": "contract backlog expanded"}],
            "contradictory": [{"evidence_id": "rag_new_counter", "text": "cash conversion weakened"}],
            "sufficiency": {"sufficient_for_synthesis": True},
        },
        "deterministic_current": {
            "company": "Northrop Grumman",
            "sector": "Industrials",
            "industry": "Aerospace & Defense",
            "price": 590.0,
            "trend": "UP",
        },
        "previous_research": {
            "research_id": "research_prior",
            "conclusion": "Maintain HOLD pending margin evidence.",
            "as_of": "2026-08-18T12:00:00+00:00",
        },
        "operator_feedback": [{"intent": "DEFER", "reason": "Need earnings evidence"}],
        "memory_context": {
            "authority": "NON_AUTHORITATIVE_CONTEXT",
            "memory_behavior_influence": "0",
            "supporting": [{"memory_id": "mem_1", "subject": "operator prefers primary filings"}],
            "counter": [],
            "conflicts": [],
        },
        "ratified_lessons": [{"lesson_id": "lesson_1", "lifecycle": "RATIFIED_CONTEXT"}],
        "financial_senses_receipts": [{"receipt_id": "fs_1", "stance": "CAUTION"}],
    }
    return build_research_prompt_context(**kwargs)


def _material_noc_result(classification: str = "STRENGTHENS") -> dict:
    return {
        "recommendation": (
            "NOC remains a HOLD in the defensive-growth role after the latest earnings review. "
            "Revenue increased 6.7% as the funded backlog supported visible multi-year demand. "
            "The B-21 program remains the most important named catalyst for future sales and margin mix. "
            "Management guidance supports continued growth but does not justify an independent ADD decision. "
            "Cash conversion is the strongest counterpoint and requires confirmation in the next filing. "
            "The standing thesis is strengthened because program funding and execution evidence improved. "
            "The thesis would be invalidated if material program cancellations accelerate or guidance is withdrawn. "
            "NOC should therefore remain held, with the CIO applying deterministic portfolio and reentry gates. "
            "This research changes evidence completeness only and grants no trading or broker authority."
        ),
        "dissent": "Free-cash-flow conversion could weaken even while reported revenue and backlog rise.",
        "confidence": 0.82,
        "classification": classification,
        "evidence_as_of": "2026-08-22T20:00:00+00:00",
        "evidence": [
            {"evidence_id": "sec_noc_10q_2026q2", "tag": "fact", "text": "NOC revenue increased 6.7%."},
            {"evidence_id": "noc_guidance_2026", "tag": "fact", "text": "Guidance retained the growth range."},
        ],
        "contradictory_evidence": [
            {"evidence_id": "noc_cash_conversion", "text": "Cash conversion weakened."},
        ],
        "reason_summary": "Fresh primary evidence strengthens, but does not independently promote, the thesis.",
        "what_changed": ["revenue evidence", "backlog evidence"],
        "what_did_not_change": ["HOLD stance", "invalidation geometry"],
        "research_gaps_remaining": ["next-quarter cash conversion"],
        "source_quality": {"grade": "PRIMARY"},
        "freshness": {"state": "CURRENT"},
        "source_refs": ["sec:noc:10-q:2026q2"],
        "thesis_stance": "HOLD",
        "provider": "governed_cloud",
        "model": "cloud-model",
    }


def test_stateful_prompt_contains_all_governed_context(tmp_path: Path, monkeypatch):
    context = _prompt_context(tmp_path, monkeypatch)
    assert context["standing_thesis"]["version"] == "symbol_noc@v7"
    assert context["previous_research_conclusion"]["research_id"] == "research_prior"
    assert context["unresolved_research_gaps"] == ["quantify B-21 margin progression"]
    assert context["deterministic_current_data"]["price"] == 590.0
    assert context["rag"]["supporting"][0]["evidence_id"] == "rag_new_support"
    assert context["rag"]["contradictory"][0]["evidence_id"] == "rag_new_counter"
    assert context["operator_feedback"][0]["intent"] == "DEFER"
    assert context["memory_context"]["memory_behavior_influence"] == "0"
    assert context["ratified_lessons"][0]["lesson_id"] == "lesson_1"
    assert context["financial_senses_receipts"][0]["receipt_id"] == "fs_1"
    assert context["authority"] == "READ_ONLY_ADVISORY"
    assert context["memory_behavior_influence"] == 0
    assert context["raw_chain_of_thought"] is False
    assert len(context["prompt_context_hash"]) == 64


def test_prompt_redacts_credential_shaped_content(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol", _fields)
    context = build_research_prompt_context(
        "NOC",
        question="token=abc123 evaluate evidence",
        root=tmp_path,
        rag_catalog={"supporting": [], "contradictory": []},
        deterministic_current={},
        previous_research={},
        operator_feedback=[{"api_key": "abc", "reason": "Bearer xyz987"}],
        memory_context={},
        ratified_lessons=[],
    )
    encoded = json.dumps(context)
    assert "abc123" not in encoded
    assert "xyz987" not in encoded
    assert '"api_key": "[REDACTED]"' in encoded


def test_delta_rejects_malformed_confidence(tmp_path: Path, monkeypatch):
    context = _prompt_context(tmp_path, monkeypatch)
    result = _material_noc_result()
    result["confidence"] = "not-a-number"
    delta = build_research_thesis_delta(
        "NOC", result, prompt_context=context, research_id="research_bad_confidence"
    )
    assert delta["confidence"] == 0.0
    assert delta["classification"] == "STRENGTHENS"


def test_noc_automatic_mint_then_no_new_info_replay(tmp_path: Path, monkeypatch):
    context = _prompt_context(tmp_path, monkeypatch)
    # Acceptance uses the fixture's standing thesis as context, while the isolated
    # store begins empty so the first accepted delta proves automatic minting.
    result = _material_noc_result()
    first = accept_research_result(
        "NOC",
        result,
        prompt_context=context,
        research_id="research_noc_1",
        root=tmp_path,
        run_id="run_noc_1",
        source_sha="abc123",
    )
    assert first["delta"]["classification"] == "STRENGTHENS"
    assert first["version_published"] is True
    assert first["new_version"] == "symbol_noc@v1"
    assert first["thesis_change_card"]["schema"] == "ThesisChangeCard@v1"

    store = CIOThesisStore(
        event_path=tmp_path / "data/cio/cio_theses.jsonl",
        projection_path=tmp_path / "data/cio/cio_theses_projection.json",
    )
    current = store.get_current("symbol_noc")
    provenance = current["write_provenance"]
    assert provenance["writer"] == "research_thesis_delta"
    assert provenance["source_research_ids"] == ["research_noc_1"]
    assert provenance["delta_id"] == first["delta"]["delta_id"]
    assert provenance["trigger"] == "research_completion"
    assert provenance["run_id"] == "run_noc_1"
    assert provenance["source_sha"] == "abc123"
    assert provenance["previous_version"] is None
    assert provenance["reason_for_change"]

    replay = accept_research_result(
        "NOC",
        result,
        prompt_context=context,
        research_id="research_noc_2",
        root=tmp_path,
        run_id="run_noc_2",
        source_sha="abc123",
    )
    assert replay["delta"]["classification"] == "NO_NEW_INFO"
    assert replay["version_published"] is False
    assert replay["publish_suppressed_reason"] == "no_material_change"
    assert store.get_current("symbol_noc")["thesis_version"] == "symbol_noc@v1"

    cards = (tmp_path / "data/cio/thesis_change_cards.jsonl").read_text().splitlines()
    assert len(cards) == 1
    deltas = (tmp_path / "data/cio/research_thesis_deltas.jsonl").read_text().splitlines()
    assert len(deltas) == 2
