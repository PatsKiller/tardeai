from pathlib import Path
from types import SimpleNamespace
import json
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import strategy_ticket_review as review


def complete_response(verdict="PASS"):
    return {
        "verdict": verdict,
        "math_check": {
            "entry_consistent": True,
            "stop_consistent": True,
            "target_consistent": True,
            "rr_recomputed": 2.0,
            "rr_matches": True,
        },
        "semantic_contradictions": [],
        "missing_evidence": [],
        "stale_inputs": [],
        "risk_objections": [],
        "questions": [],
        "evidence_citations": ["deterministic_validation.recomputed.risk_reward"],
    }


def test_review_packet_is_curated_and_unanchored():
    facts = {
        "live_price": 100.0,
        "atr": 3.0,
        "rvol": 1.1,
        "float_m": 500.0,
        "live_price_as_of": "2026-07-25T00:00:00Z",
        "analyst_rating": "strong_buy",
        "latest_recommendation": "BUY",
        "hermes_rank": 1,
        "fundamentals": {
            "market_cap_usd_millions": 20_000,
            "pe": 20,
            "profit_margin_pct": 18,
            "analyst_rating": "strong_buy",
        },
        "technical_state": {
            "overall_freshness": "CURRENT",
            "overall_direction": "BULLISH",
            "source_hash": "abc123",
        },
        "deterministic_thesis": {"thesis_state": "CONSTRUCTIVE"},
        "data_quality": {"state": "FRESH"},
        "catalysts": [{
            "headline": "Contract awarded",
            "published_at": "2026-07-24T12:00:00Z",
            "type": "contract",
            "confidence": 0.9,
        }],
    }
    validation = {
        "state": "PASS",
        "recomputed": {"risk_reward": 2.0},
        "quality_admission": {"state": "ADMITTED", "new_entry_allowed": True},
        "ticket_hash": "ticket-hash",
        "facts_hash": "facts-hash",
    }
    packet = review.build_review_packet(
        "TEST",
        {"structure": "PULLBACK_SWING", "limit_price": 100, "stop_price": 95,
         "targets": [110], "risk_reward": 2.0, "mechanics_current": True},
        facts,
        validation,
    )
    serialized = json.dumps(packet).lower()

    assert packet["contract"] == "watch-ticket-independent-review-v2"
    assert packet["deterministic_validation"]["quality_admission"]["state"] == "ADMITTED"
    assert packet["technical_snapshot"]["overall_freshness"] == "CURRENT"
    assert packet["fundamentals"]["market_cap_usd_millions"] == 20_000
    assert "analyst_rating" not in serialized
    assert "latest_recommendation" not in serialized
    assert "hermes_rank" not in serialized
    assert "confidence" not in packet["catalysts"][0]


def test_strict_parser_rejects_partial_json():
    assert review._parse('{"verdict":"PASS"}') is None
    partial_math = complete_response()
    partial_math["math_check"].pop("rr_matches")
    assert review._parse(json.dumps(partial_math)) is None


def test_strict_parser_accepts_complete_contract():
    parsed = review._parse("```json\n" + json.dumps(complete_response("caution")) + "\n```")
    assert parsed is not None
    assert parsed["verdict"] == "CAUTION"
    assert parsed["math_check"]["rr_recomputed"] == 2.0


def test_oauth_lane_uses_prompt_first_keyword_contract(monkeypatch):
    calls = []

    def generate(prompt, *, lane):
        calls.append((prompt, lane))
        return {"text": json.dumps(complete_response()), "model": f"fake-{lane}"}

    fake = SimpleNamespace(
        available=lambda lane: True,
        generate=generate,
    )
    monkeypatch.setitem(sys.modules, "llm_lane", fake)
    result = review.run_oauth_critic(
        "grok",
        "TEST",
        {"structure": "PULLBACK_SWING", "limit_price": 100, "stop_price": 95,
         "targets": [110], "risk_reward": 2.0, "mechanics_current": True},
        {"live_price": 100, "atr": 3},
        {"state": "PASS", "ticket_hash": "t", "facts_hash": "f"},
    )

    assert result["verdict"] == "PASS"
    assert result["model"] == "fake-grok"
    assert len(calls) == 1
    assert calls[0][1] == "grok"
    assert "max_tokens" not in calls[0][0]
