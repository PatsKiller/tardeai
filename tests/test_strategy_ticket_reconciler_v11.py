from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import strategy_ticket_reconciler as reconciler


def admitted_validation(state="PASS"):
    return {
        "state": state,
        "ticket_hash": "ticket-1",
        "warnings": ["technical warning"] if state == "REVIEW_REQUIRED" else [],
        "hard_failures": [],
        "quality_admission": {
            "state": "ADMITTED",
            "new_entry_allowed": True,
            "reasons": [],
        },
    }


def critic(verdict, family, ticket_hash="ticket-1"):
    return {
        "verdict": verdict,
        "provider_family": family,
        "ticket_hash_reviewed": ticket_hash,
    }


def test_missing_validation_is_not_promoted_to_pass():
    result = reconciler.reconcile({}, {})
    assert result["state"] == "DETERMINISTIC_NOT_RUN"
    assert result["proposal_allowed"] is False
    assert result["paid_lane_called"] is False


def test_synthetic_pass_without_quality_record_is_rejected():
    result = reconciler.reconcile(
        {"state": "PASS"},
        {
            "local": critic("PASS", "LOCAL_OLLAMA"),
            "grok": critic("PASS", "XAI"),
        },
        premium={"verdict": "PASS"},
    )
    assert result["state"] == "QUALITY_NOT_ASSESSED"
    assert result["proposal_allowed"] is False
    assert result["paid_lane_called"] is False


def test_deterministic_failure_cannot_be_overridden_by_unanimous_models_or_premium():
    result = reconciler.reconcile(
        {"state": "FAIL", "hard_failures": ["quality admission failed"]},
        {
            "local": critic("PASS", "LOCAL_OLLAMA"),
            "grok": critic("PASS", "XAI"),
            "chatgpt": critic("PASS", "OPENAI"),
        },
        premium={"verdict": "PASS"},
    )
    assert result["state"] == "DETERMINISTIC_FAIL"
    assert result["proposal_allowed"] is False


def test_review_required_is_not_called_deterministically_verified():
    result = reconciler.reconcile(
        admitted_validation("REVIEW_REQUIRED"),
        {
            "local": critic("PASS", "LOCAL_OLLAMA"),
            "grok": critic("PASS", "XAI"),
        },
    )
    assert result["state"] == "DETERMINISTIC_REVIEW_REQUIRED"
    assert result["proposal_allowed"] is False
    assert result["premium_recommended"] is True
    assert "verified" not in result["detail"].lower()


def test_non_admitted_quality_is_sovereign_even_with_validation_pass():
    validation = admitted_validation()
    validation["quality_admission"] = {
        "state": "RESEARCH_ONLY",
        "new_entry_allowed": False,
        "reasons": ["fundamental evidence incomplete"],
    }
    result = reconciler.reconcile(
        validation,
        {"grok": critic("PASS", "XAI")},
        premium={"verdict": "PASS"},
    )
    assert result["state"] == "QUALITY_NOT_ADMITTED"
    assert result["proposal_allowed"] is False


def test_two_independent_passes_allow_free_review_state():
    result = reconciler.reconcile(
        admitted_validation(),
        {
            "local": critic("PASS", "LOCAL_OLLAMA"),
            "grok": critic("PASS", "XAI"),
        },
    )
    assert result["state"] == "VERIFIED_FREE_REVIEW"
    assert result["proposal_allowed"] is True
    assert result["premium_recommended"] is False


def test_split_review_recommends_but_does_not_call_paid_lane():
    result = reconciler.reconcile(
        admitted_validation(),
        {
            "local": critic("PASS", "LOCAL_OLLAMA"),
            "grok": critic("REJECT", "XAI"),
        },
    )
    assert result["state"] == "REVIEW_SPLIT"
    assert result["proposal_allowed"] is False
    assert result["premium_recommended"] is True
    assert result["paid_lane_called"] is False


def test_no_completed_critic_is_review_unavailable_not_verified():
    result = reconciler.reconcile(
        admitted_validation(),
        {"local": critic("UNAVAILABLE", "LOCAL_OLLAMA")},
    )
    assert result["state"] == "REVIEW_UNAVAILABLE"
    assert result["proposal_allowed"] is False
    assert result["premium_recommended"] is True
    assert "deterministic PASS" in result["detail"]
