from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import research_due_diligence as rdd
import specialized_research_review as review


def diligence(state="PASS"):
    check_state = rdd.CHECK_PASS if state == "PASS" else rdd.CHECK_FAIL
    return rdd.evaluate(
        domain="sector",
        subject={"sector": "Technology"},
        checks=[rdd.check("math", check_state,
                          "math reproduces" if check_state == rdd.CHECK_PASS else "math failed",
                          evidence_refs=["prices"])],
        sources=[rdd.source_ref(
            source_id="prices", provider="test", as_of="2026-07-25",
            calculation_version="v1", quality="ok", payload={"px": 1},
        )],
        evidence={"rs20": 3.0},
    )


def test_review_packet_is_curated_and_deterministic_remains_sovereign():
    packet = review.build_review_packet(diligence())
    assert packet["contract"] == "specialized-research-independent-review-v1"
    assert packet["deterministic_state"] == "PASS"
    assert packet["authority"]["critic_may_create_or_repair_mechanics"] is False
    assert packet["authority"]["critic_may_activate_recommendation"] is False
    assert "other critic verdicts" in packet["excluded_anchoring_inputs"]


def test_strict_parser_rejects_incomplete_or_unknown_schema():
    assert review._parse('{"verdict":"PASS"}') is None
    assert review._parse('{"verdict":"MAYBE","summary":"x","contradictions":[],"missing_evidence":[],"stale_sources":[],"methodology_objections":[],"questions":[],"evidence_citations":[]}') is None
    parsed = review._parse('{"verdict":"CAUTION","summary":"check breadth","contradictions":[],"missing_evidence":["coverage"],"stale_sources":[],"methodology_objections":[],"questions":[],"evidence_citations":["coverage.required_sources"]}')
    assert parsed["verdict"] == "CAUTION"


def test_blocked_packet_skips_all_model_lanes():
    reviews = review.run_free_reviews(diligence("BLOCKED"), lanes=("local", "grok", "chatgpt"))
    assert reviews["_meta"]["completed"] == 0
    assert reviews["_meta"]["paid_lane_called"] is False
    assert "skipped" in reviews["_meta"]
    assert set(reviews) == {"_meta"}


def test_source_has_no_paid_or_execution_authority():
    source = (SCRIPTS / "specialized_research_review.py").read_text().lower()
    assert "paid_lane_automatic" not in source
    assert '"paid_lane_called": false' in source
    for forbidden in (
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
        "premium_review(",
    ):
        assert forbidden not in source
    assert "llm_lane.generate(_system +" in source
    assert "lane=lane" in source
