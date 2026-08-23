from __future__ import annotations

import pytest

from scripts.lib.research_contradiction import assess_candidate, find_contradiction_candidates, persist_candidates
from scripts.lib.research_metadata import build_research_metadata


def _metadata(stance="BULLISH"):
    return build_research_metadata(
        symbol="NOC",
        symbol_profile={
            "sector": "Industrials",
            "industry": "Aerospace & Defense",
            "market_cap_b": 85,
            "index_memberships": ["S&P 500"],
            "provenance": {"source": "symbol_profiles", "source_record_id": "NOC:42", "as_of": "2026-08-23"},
        },
        market_data={
            "price": 590,
            "avg_dollar_volume": 125_000_000,
            "provenance": {"source": "market_quotes", "source_record_id": "mq:42", "as_of": "2026-08-23"},
        },
        analyst_data={
            "analyst_rating": "HOLD",
            "street_mean_target": 620,
            "revision_direction": "UP",
            "verified_producer": True,
            "provenance": {"source": "analyst_consensus_history", "source_record_id": "ach:42", "as_of": "2026-08-23"},
        },
        judgment={
            "theme": "DEFENSE",
            "stance": stance,
            "conviction": "HIGH",
            "catalyst_type": "GUIDANCE",
            "risk_type": "EXECUTION",
            "time_horizon": "MONTHS",
            "named_entities": ["B-21"],
            "made_up": "DROP_ME",
        },
        provider="deepseek",
        model="deepseek-v4-flash",
        research_id="r42",
    )


def test_factual_and_judgment_provenance_are_separate():
    metadata = _metadata()
    assert metadata["provenance_classes_mixed"] is False
    assert metadata["factual"]["sector"]["provenance_class"] == "FACTUAL"
    assert metadata["factual"]["street_mean_target"]["source"] == "analyst_consensus_history"
    assert metadata["factual"]["market_cap_band"]["value"] == "LARGE"
    assert metadata["factual"]["liquidity_band"]["value"] == "HIGH"
    assert metadata["judgment"]["provenance_class"] == "JUDGMENT"
    assert metadata["judgment"]["provider"] == "deepseek"
    assert "made_up" not in metadata["judgment"]["tags"]


def test_unverified_street_target_and_unproven_facts_are_dropped():
    metadata = build_research_metadata(
        symbol="NOC",
        symbol_profile={"sector": "Industrials"},
        market_data={"price": 590},
        analyst_data={
            "street_mean_target": 999,
            "verified_producer": False,
            "provenance": {"source": "model", "source_record_id": "answer:1"},
        },
        judgment={},
        provider="deepseek",
        model="flash",
        research_id="r1",
    )
    assert metadata["factual"] == {}


def test_contradiction_candidate_and_independent_assessment(tmp_path):
    records = [
        {"delta_id": "d1", "symbol": "NOC", "classification": "STRENGTHENS", "metadata": _metadata("BULLISH"), "source_refs": ["sec:1"]},
        {"delta_id": "d2", "symbol": "LHX", "classification": "WEAKENS", "metadata": _metadata("BEARISH"), "source_refs": ["sec:2"]},
    ]
    candidates = find_contradiction_candidates(records)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "CANDIDATE"
    assert candidate["self_validated"] is False
    assert candidate["thesis_rewritten"] is False
    result = persist_candidates(records, path=tmp_path / "candidates.jsonl")
    replay = persist_candidates(records, path=tmp_path / "candidates.jsonl")
    assert result["written"] == 1
    assert replay["written"] == 0

    with pytest.raises(ValueError, match="self_validation_forbidden"):
        assess_candidate(
            candidate,
            assessor_id="deepseek",
            assessor_provider="deepseek",
            artifact_producers=["deepseek"],
            assessment="conflict",
            evidence_refs=[],
        )
    assessed = assess_candidate(
        candidate,
        assessor_id="challenger-1",
        assessor_provider="claude",
        artifact_producers=["deepseek"],
        assessment="Both claims depend on different guidance windows.",
        evidence_refs=["sec:1", "sec:2"],
    )
    assert assessed["status"] == "ASSESSED"
    assert assessed["thesis_rewritten"] is False
