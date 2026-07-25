from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import research_due_diligence as rdd


def good_source(source_id="prices"):
    return rdd.source_ref(
        source_id=source_id,
        provider="test-provider",
        as_of="2026-07-25T16:00:00+00:00",
        calculation_version="test-v1",
        quality="ok",
        required=True,
        payload={"value": 1},
    )


def test_policy_is_versioned_and_matches_contract():
    policy = rdd.load_policy()
    assert policy["version"] == "research-due-diligence-policy-v1"
    assert policy["contract"] == rdd.CONTRACT_VERSION
    assert set(policy["required_source_fields"]) >= {
        "source_id", "provider", "as_of", "calculation_version",
        "quality", "content_hash",
    }


def test_all_required_evidence_and_checks_pass():
    packet = rdd.evaluate(
        domain="sector",
        subject={"sector": "Technology", "etf": "XLK"},
        checks=[rdd.check("math", rdd.CHECK_PASS, "math reproduces", evidence_refs=["prices"])],
        sources=[good_source()],
        evidence={"rs20": 3.2},
        policy_version="policy-v1",
        calculation_version="calc-v1",
    )
    assert packet["deterministic_state"] == "PASS"
    assert packet["coverage"]["required_source_coverage_pct"] == 100.0
    assert packet["downstream"]["proposal_or_recommendation_eligible"] is True
    assert packet["authority"]["broker_or_order_action"] is False
    assert packet["model_oversight"]["may_override_deterministic_state"] is False
    assert packet["policy_requirements"]


def test_warning_requires_specialist_review_but_does_not_grant_release():
    packet = rdd.evaluate(
        domain="industry",
        subject={"industry": "Semiconductors"},
        checks=[rdd.check("close", rdd.CHECK_WARN, "midday research only", evidence_refs=["groups"])],
        sources=[good_source("groups")],
    )
    assert packet["deterministic_state"] == "REVIEW_REQUIRED"
    assert packet["downstream"]["research_complete"] is False
    assert packet["downstream"]["specialist_review_required"] is True
    assert packet["model_oversight"]["allowed"] is True


def test_stale_required_source_blocks_even_when_domain_check_passes():
    stale = rdd.source_ref(
        source_id="breadth",
        provider="test-provider",
        as_of="2026-07-01",
        calculation_version="breadth-v1",
        quality="ok",
        stale=True,
        payload={"coverage": 100},
    )
    packet = rdd.evaluate(
        domain="sector",
        subject={"sector": "Energy"},
        checks=[rdd.check("math", rdd.CHECK_PASS, "math reproduces", evidence_refs=["breadth"])],
        sources=[stale],
    )
    assert packet["deterministic_state"] == "BLOCKED"
    assert any("stale" in reason for reason in packet["hard_failures"])
    assert packet["model_oversight"]["allowed"] is False


def test_missing_provider_or_calculation_version_fails_closed():
    incomplete = rdd.source_ref(
        source_id="fundamentals",
        provider=None,
        as_of="2026-07-25",
        calculation_version=None,
        quality="ok",
        payload={"pe": 20},
    )
    packet = rdd.evaluate(
        domain="watch",
        subject={"symbol": "AAPL"},
        checks=[rdd.check("facts", rdd.CHECK_PASS, "facts present", evidence_refs=["fundamentals"])],
        sources=[incomplete],
    )
    assert packet["deterministic_state"] == "BLOCKED"
    failures = " ".join(packet["hard_failures"])
    assert "provider" in failures
    assert "calculation_version" in failures


def test_unknown_evidence_reference_fails_closed():
    packet = rdd.evaluate(
        domain="defense",
        subject={"card_id": "x"},
        checks=[rdd.check("capacity", rdd.CHECK_PASS, "capacity present", evidence_refs=["missing-source"])],
        sources=[good_source("allocation")],
    )
    assert packet["deterministic_state"] == "BLOCKED"
    assert "unknown evidence sources" in " ".join(packet["hard_failures"])


def test_packet_hash_is_deterministic_and_excludes_wall_clock():
    kwargs = dict(
        domain="watch",
        subject={"symbol": "AAPL"},
        checks=[rdd.check("quality", rdd.CHECK_PASS, "admitted", evidence_refs=["facts"])],
        sources=[good_source("facts")],
        evidence={"quality": "ADMITTED"},
    )
    first = rdd.evaluate(**kwargs, generated_at="2026-07-25T12:00:00+00:00")
    second = rdd.evaluate(**kwargs, generated_at="2026-07-25T13:00:00+00:00")
    assert first["packet_hash"] == second["packet_hash"]


def test_aggregate_blocks_when_a_specialized_child_blocks():
    passed = rdd.evaluate(
        domain="sector",
        subject={"sector": "Technology"},
        checks=[rdd.check("math", rdd.CHECK_PASS, "ok", evidence_refs=["s"])],
        sources=[good_source("s")],
        calculation_version="sector-test-v1",
    )
    blocked = rdd.evaluate(
        domain="industry",
        subject={"industry": "Unknown"},
        checks=[rdd.check("mapping", rdd.CHECK_FAIL, "unmapped", evidence_refs=["i"])],
        sources=[good_source("i")],
        calculation_version="industry-test-v1",
    )
    parent = rdd.aggregate(
        domain="defense",
        subject={"card_id": "rotate-in"},
        children=[passed, blocked],
    )
    assert parent["deterministic_state"] == "BLOCKED"
    assert parent["authority"]["recommendation_activation"] is False
