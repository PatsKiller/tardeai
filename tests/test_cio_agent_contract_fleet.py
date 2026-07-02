#!/usr/bin/env python3
"""Fleet parity: shared cio_agent_v2 contract module tests."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from cio_agent_contract import (
    AGENT_JSON_CONTRACT_VERSION,
    build_proposal_vote_json_schema,
    merge_structured_into_result,
    normalize_evidence,
    normalize_hermes_evidence,
    parse_agent_result,
    parse_cloud_review_result,
    parse_external_research_result,
    parse_hermes_topic_result,
    parse_holdings_health_result,
    parse_portfolio_brief_result,
    parse_proposal_intelligence_result,
    parse_proposal_vote_result,
    parse_synthesis_result,
)


def test_contract_version():
    assert "cio_agent_v2" in AGENT_JSON_CONTRACT_VERSION
    assert "structured_evidence" in AGENT_JSON_CONTRACT_VERSION


def test_proposal_vote_parser():
    raw = json.dumps({
        "vote": "CAUTIOUS_TEST",
        "confidence": 72,
        "summary": "Setup acceptable for paper test",
        "concerns": ["Sector weak"],
        "required_followups": [],
        "evidence": [{"tag": "technical", "text": "RSI 58"}],
        "data_i_doubt": "news may be 2d stale",
    })
    p = parse_proposal_vote_result(raw)
    assert p["vote"] == "CAUTIOUS_TEST"
    assert p["evidence"][0]["tag"] == "technical"
    assert p["agent_contract"] == AGENT_JSON_CONTRACT_VERSION


def test_proposal_intelligence_parser():
    raw = json.dumps({
        "setup_narrative": "ABC gap play",
        "strategy_fit_assessment": "Matches momentum_scalp",
        "technical_assessment": "RSI 62 above 50",
        "catalyst_assessment": "Verified earnings",
        "risk_assessment": "Stop 8% away",
        "kill_conditions": ["Break below VWAP"],
        "approve_case": "RVOL 6x",
        "reject_case": "Sector -6%",
        "verdict": "CAUTIOUS_PAPER_TEST",
        "conviction": "MEDIUM",
        "confidence": 0.65,
        "evidence": [{"tag": "fact", "text": "RVOL 6.2x"}],
        "data_i_doubt": "none",
    })
    p = parse_proposal_intelligence_result(raw)
    assert p["summary"] == "ABC gap play"
    assert len(p["kill_conditions"]) == 1
    assert p["evidence"][0]["text"] == "RVOL 6.2x"


def test_portfolio_brief_parser():
    raw = json.dumps({
        "summary": "Portfolio healthy overall",
        "key_actions": "Review SCHD trim",
        "watch_holdings": [{"symbol": "SCHD", "status": "WATCH", "reason": "15% weight"}],
        "news_impacts": [{"symbol": "V", "impact": "Stable payments"}],
        "evidence": [{"tag": "risk", "text": "V concentration 18%"}],
        "data_i_doubt": "401k export stale",
    })
    p = parse_portfolio_brief_result(raw)
    assert p["key_actions"] == "Review SCHD trim"
    assert p["watch_holdings"][0]["symbol"] == "SCHD"


def test_merge_structured_defaults():
    base = merge_structured_into_result({"vote": "REJECT"})
    assert base["evidence"] == []
    assert base["data_i_doubt"] == "none"


def test_proposal_schema_includes_contract():
    schema = build_proposal_vote_json_schema()
    assert "agent_contract" in schema or "cio_agent_v2" in schema
    assert "evidence" in schema


def test_parse_agent_result_shared():
    raw = json.dumps({
        "summary": "Hold",
        "recommendation": "HOLD",
        "confidence": 0.8,
        "evidence": [{"tag": "fact", "text": "3.2% yield"}],
        "data_i_doubt": "none",
    })
    p = parse_agent_result(raw)
    assert p["recommendation"] == "HOLD"
    assert normalize_evidence([{"tag": "bogus", "text": "x"}])[0]["tag"] == "fact"


def test_synthesis_parser():
    raw = json.dumps({
        "recommendation": "HOLD",
        "confidence": 0.72,
        "action": "Hold position",
        "synthesis_narrative": "Committee aligned on income stability.",
        "conflicts": [],
        "evidence": [{"tag": "fact", "text": "3.2% yield"}],
        "data_i_doubt": "none",
    })
    p = parse_synthesis_result(raw)
    assert p["recommendation"] == "HOLD"
    assert p["synthesis_narrative"].startswith("Committee")


def test_external_research_parser():
    raw = json.dumps({
        "recommendation": "Cautious hold",
        "evidence": ["RSI elevated", "Sector weak"],
        "confidence": 0.6,
        "risk_flags": ["stale news"],
    })
    p = parse_external_research_result(raw)
    assert len(p["evidence"]) == 2
    assert p["evidence"][0]["tag"] == "fact"


def test_hermes_evidence_mapper():
    mapped = normalize_hermes_evidence({
        "facts": ["Revenue grew 12%"],
        "challenge_points": ["Payout ratio high"],
    })
    assert mapped[0]["tag"] == "fact"
    assert mapped[1]["tag"] == "risk"


def test_holdings_health_parser():
    raw = json.dumps({
        "health": "WATCH",
        "confidence": 65,
        "action": "HOLD",
        "reasoning": "Sector headwind",
        "evidence": [{"tag": "technical", "text": "RSI 71"}],
        "data_i_doubt": "news stale",
    })
    p = parse_holdings_health_result(raw)
    assert p["health"] == "WATCH"


def test_cloud_review_parser():
    raw = json.dumps({
        "verdict": "CAUTION",
        "assessment": "Local model over-weighted RSI",
        "concerns": ["Missing catalyst context"],
        "corrections": ["Re-check catalyst freshness"],
    })
    p = parse_cloud_review_result(raw)
    assert p["verdict"] == "CAUTION"
    assert len(p["evidence"]) >= 1


def test_hermes_topic_parser():
    raw = json.dumps({
        "summary": "Medicaid lookback rules require planning ahead for asset transfers.",
        "thesis": "Plan 5-year lookback before large gifts.",
        "considerations": ["5-year lookback", "IRMAA brackets"],
        "confidence": 0.7,
    })
    p = parse_hermes_topic_result(raw)
    assert "Medicaid" in p["summary"]
    assert p["agent_contract"] == AGENT_JSON_CONTRACT_VERSION


def main():
    test_contract_version()
    test_proposal_vote_parser()
    test_proposal_intelligence_parser()
    test_portfolio_brief_parser()
    test_merge_structured_defaults()
    test_proposal_schema_includes_contract()
    test_parse_agent_result_shared()
    test_synthesis_parser()
    test_external_research_parser()
    test_hermes_evidence_mapper()
    test_holdings_health_parser()
    test_cloud_review_parser()
    test_hermes_topic_parser()
    print("test_cio_agent_contract_fleet: 13 passed")


if __name__ == "__main__":
    main()