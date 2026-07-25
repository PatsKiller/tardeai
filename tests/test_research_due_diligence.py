from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import research_due_diligence as diligence
import specialized_research_pipeline as pipeline


def source(quality="ok"):
    return {
        "provider": "fixture",
        "as_of": "2026-07-25T12:00:00+00:00",
        "quality": quality,
        "provenance_ref": "fixture-hash",
    }


def verified(domain="SECTOR", subject="Technology"):
    return diligence.evaluate(
        domain=domain,
        subject=subject,
        methodology_version="fixture-v1",
        as_of="2026-07-25T12:00:00+00:00",
        sources=[source()],
        deterministic_checks=[{"name": "math", "passed": True}],
        coverage={"required": 1, "observed": 1},
        freshness={"state": "CURRENT"},
    )


def test_verified_research_is_only_operator_review_eligible():
    packet = verified()
    assert packet["state"] == "VERIFIED"
    assert packet["release_allowed"] is True
    assert packet["authority"]["operator_review_eligible"] is True
    assert packet["authority"]["external_action_allowed"] is False
    assert packet["oversight"]["models_may_override"] is False


def test_missing_provenance_is_insufficient_not_model_repairable():
    packet = diligence.evaluate(
        domain="INDUSTRY",
        subject="Semiconductors",
        methodology_version="industry-v1",
        as_of="2026-07-25T12:00:00+00:00",
        sources=[{"provider": "fixture", "as_of": "2026-07-25", "quality": "ok"}],
        deterministic_checks=[{"name": "quadrant", "passed": True}],
    )
    assert packet["state"] == "INSUFFICIENT_EVIDENCE"
    assert packet["release_allowed"] is False
    assert packet["oversight"]["models_allowed"] is False


def test_hard_deterministic_failure_is_rejected_even_with_reviews():
    packet = diligence.evaluate(
        domain="DEFENSE",
        subject="Rotate into Technology",
        methodology_version="defense-v1",
        as_of="2026-07-25T12:00:00+00:00",
        sources=[source()],
        deterministic_checks=[{
            "name": "account_capacity",
            "passed": False,
            "reason": "account capacity unavailable",
        }],
        oversight={"local": {"verdict": "PASS"}, "chatgpt": {"verdict": "PASS"}},
    )
    assert packet["state"] == "REJECTED"
    assert packet["release_allowed"] is False
    assert packet["oversight"]["models_may_override"] is False


def test_warning_requires_operator_review_not_release():
    packet = diligence.evaluate(
        domain="SECTOR",
        subject="Industrials",
        methodology_version="sector-v1",
        as_of="2026-07-25T12:00:00+00:00",
        sources=[source()],
        deterministic_checks=[{
            "name": "breadth",
            "passed": False,
            "severity": "warning",
            "reason": "narrow participation",
        }],
    )
    assert packet["state"] == "REVIEW_REQUIRED"
    assert packet["release_allowed"] is False
    assert packet["oversight"]["models_allowed"] is True


def test_proposal_gate_refuses_one_unverified_specialized_dependency():
    good = verified("SECTOR", "Technology")
    bad = diligence.evaluate(
        domain="INDUSTRY",
        subject="Software",
        methodology_version="industry-v1",
        as_of="2026-07-25T12:00:00+00:00",
        sources=[source("missing")],
        deterministic_checks=[{"name": "quadrant", "passed": True}],
    )
    proposal = diligence.proposal_gate("Add software exposure", [good, bad])
    assert proposal["state"] in {"REJECTED", "INSUFFICIENT_EVIDENCE"}
    assert proposal["release_allowed"] is False


def test_proposal_gate_requires_nonempty_specialized_research():
    proposal = diligence.proposal_gate("Empty proposal", [])
    assert proposal["state"] == "INSUFFICIENT_EVIDENCE"
    assert proposal["release_allowed"] is False


def test_pipeline_propagates_release_state_to_candidates():
    snapshot = {
        "captured_at": "2026-07-25T20:18:00+00:00",
        "capture_kind": "close",
        "calculation_version": "industry-v1",
        "industries": [{
            "industry": "Software - Infrastructure",
            "sector": "Technology",
            "rel1w": 1.2,
            "rel1m": 2.4,
            "state": "LEADING",
            "stocks": 20,
            "quality": "same_vendor_same_run",
            "quarantined": False,
            "truth": {
                "source": "finviz_elite_view_141",
                "as_of": "2026-07-25T20:18:00+00:00",
                "quality": "same_vendor_same_run",
                "hash": "industry-hash",
                "calculation_version": "industry-v1",
            },
        }],
        "candidates": {
            "watch_rail": [{"industry": "Software - Infrastructure", "sector": "Technology"}],
            "defensive_short_pool": [],
        },
    }
    enriched = pipeline.enrich_industry_snapshot(snapshot)
    row = enriched["industries"][0]
    candidate = enriched["candidates"]["watch_rail"][0]
    assert row["due_diligence"]["contract"] == "research-due-diligence-v1"
    assert candidate["due_diligence"]["evidence_hash"] == row["due_diligence"]["evidence_hash"]
    assert candidate["proposal_research_eligible"] is row["proposal_research_eligible"]
