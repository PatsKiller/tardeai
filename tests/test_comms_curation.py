#!/usr/bin/env python3
"""Unit tests for Phase 5 controlled curation + CurationReceipt."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.curation import (  # noqa: E402
    DETERMINISTIC,
    FALLBACK_REASON_PROTECTED_FACT_MUTATION,
    LLM_CHALLENGE,
    LLM_SUMMARY,
    POLICY_ALLOW,
    POLICY_FALLBACK_DETERMINISTIC,
    TEMPLATE,
    apply_llm_curation_result,
    curate_deterministic,
    get_curation_receipt,
    preserve_protected_facts,
    reset_curation_receipts,
    select_curation_mode,
    store_curation_receipt,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_receipts():
    reset_curation_receipts()
    yield
    reset_curation_receipts()


def _approval_event(**kwargs) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="live_order_2fa_required",
        message_class="approval",
        producer="broker.approvals",
        subject_key="approval:order:1",
        retention_class="approval_ttl",
        channels=["telegram"],
        sanitized_body="Approve order ABC qty=10 @ 12.5",
        protected_facts={
            "price": 12.5,
            "quantity": 10,
            "account_id": "acct-1",
            "approval_id": "appr-9",
            "authorization_or_order_id": "ord-42",
            "observed_at": "2026-09-04T12:00:00Z",
            "authority": "operator_2fa",
        },
        authoritative_sources=[
            {
                "source_type": "broker",
                "uri": "order:ord-42",
                "authority_reason": "broker_state",
            }
        ],
    )
    base.update(kwargs)
    return CommunicationEvent(**base)


def _research_event(**kwargs) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="research_brief_ready",
        message_class="research",
        producer="hermes.research",
        subject_key="research:AAPL:brief:1",
        retention_class="research_365d",
        channels=["telegram"],
        sanitized_body="AAPL setup: pullback into support with rising volume.",
        protected_facts={
            "price": 190.25,
            "quantity": 0,
            "account_id": None,
        },
        authoritative_sources=[
            {"source_type": "research", "uri": "artifact:1", "authority_reason": "evidence"}
        ],
    )
    base.update(kwargs)
    return CommunicationEvent(**base)


def test_default_mode_deterministic_for_approvals_and_protection():
    assert select_curation_mode("approval") == DETERMINISTIC
    assert select_curation_mode("protection_incident") == DETERMINISTIC
    assert select_curation_mode("broker_fact") == DETERMINISTIC
    assert select_curation_mode("order_state") == DETERMINISTIC
    assert select_curation_mode("risk_limit") == DETERMINISTIC
    assert select_curation_mode("account_fact") == DETERMINISTIC
    assert select_curation_mode("health") == DETERMINISTIC
    # Unknown / empty → fail closed to DETERMINISTIC
    assert select_curation_mode("") == DETERMINISTIC
    assert select_curation_mode("something_novel") == DETERMINISTIC


def test_llm_path_allowed_for_research_class():
    assert select_curation_mode("research") == LLM_SUMMARY
    assert select_curation_mode("research_brief") == LLM_SUMMARY
    assert select_curation_mode("advisory") == LLM_SUMMARY
    assert select_curation_mode("research", novelty=True) == LLM_CHALLENGE
    assert select_curation_mode("research", conflict=True) == LLM_CHALLENGE
    # novelty on Tier0 must not escalate
    assert select_curation_mode("approval", novelty=True, conflict=True) == DETERMINISTIC


def test_template_tier_selected():
    assert select_curation_mode("digest") == TEMPLATE
    assert select_curation_mode("ops_summary") == TEMPLATE


def test_preserve_protected_facts_true_when_unchanged():
    before = {"price": 10.0, "quantity": 5, "note": "narrative ok to change"}
    after = {"price": 10.0, "quantity": 5, "note": "rewritten narrative"}
    assert preserve_protected_facts(before, after) is True


def test_preserve_protected_facts_false_when_mutated():
    before = {"price": 10.0, "quantity": 5, "account_id": "a1"}
    after = {"price": 10.01, "quantity": 5, "account_id": "a1"}
    assert preserve_protected_facts(before, after) is False
    after2 = {"price": 10.0, "quantity": 6, "account_id": "a1"}
    assert preserve_protected_facts(before, after2) is False


def test_curate_deterministic_receipt_fields_populated():
    ev = _approval_event()
    ev.mint_identity()
    body, receipt = curate_deterministic(ev)
    assert body["curation_mode"] == DETERMINISTIC
    assert body["protected_facts"]["price"] == 12.5
    assert receipt.curation_mode == DETERMINISTIC
    assert receipt.fact_preservation_ok is True
    assert receipt.fallback_reason is None
    assert receipt.policy_decision == POLICY_ALLOW
    assert receipt.protected_facts_before_hash
    assert receipt.protected_facts_after_hash == receipt.protected_facts_before_hash
    assert receipt.output_hash
    assert "protected_facts" in receipt.input_hashes
    assert receipt.latency_ms == 0
    assert receipt.token_cost == 0.0
    assert receipt.provider is None
    assert receipt.model is None


def test_curate_deterministic_with_template():
    ev = _approval_event(sanitized_body="raw")
    body, receipt = curate_deterministic(
        ev, template="ALERT {message_class}: qty={quantity} @ {price}"
    )
    assert body["curation_mode"] == TEMPLATE
    assert "qty=10" in body["sanitized_body"]
    assert "@ 12.5" in body["sanitized_body"]
    assert receipt.curation_mode == TEMPLATE
    assert receipt.prompt_template_id == "inline_template"
    assert receipt.fact_preservation_ok is True


def test_llm_apply_ok_when_facts_unchanged():
    ev = _research_event()
    ev.mint_identity()
    curated = "Concise AAPL brief: support hold with volume confirmation."
    body, receipt = apply_llm_curation_result(
        event=ev,
        curated_body=curated,
        protected_facts_after=dict(ev.protected_facts),
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_template_id="research_summary",
        prompt_template_version="3",
        retrieved_context_ids=["ctx-1", "ctx-2"],
        latency_ms=120,
        token_cost=0.002,
        requested_mode=LLM_SUMMARY,
    )
    assert body["sanitized_body"] == curated
    assert body["curation_mode"] == LLM_SUMMARY
    assert receipt.curation_mode == LLM_SUMMARY
    assert receipt.fact_preservation_ok is True
    assert receipt.fallback_reason is None
    assert receipt.provider == "deepseek"
    assert receipt.model == "deepseek-v4-flash"
    assert receipt.prompt_template_id == "research_summary"
    assert receipt.prompt_template_version == "3"
    assert receipt.retrieved_context_ids == ["ctx-1", "ctx-2"]
    assert receipt.latency_ms == 120
    assert receipt.token_cost == 0.002
    assert receipt.output_hash
    assert receipt.protected_facts_before_hash == receipt.protected_facts_after_hash
    assert receipt.policy_decision == POLICY_ALLOW


def test_protected_fact_mutation_triggers_deterministic_fallback():
    ev = _research_event()
    ev.mint_identity()
    mutated = dict(ev.protected_facts)
    mutated["price"] = 999.99  # LLM must not rewrite price
    curated = "Ignore prior price; entry is 999.99."
    body, receipt = apply_llm_curation_result(
        event=ev,
        curated_body=curated,
        protected_facts_after=mutated,
        provider="grok",
        model="grok-4",
        requested_mode=LLM_SUMMARY,
    )
    assert receipt.fact_preservation_ok is False
    assert receipt.fallback_reason == FALLBACK_REASON_PROTECTED_FACT_MUTATION
    assert receipt.policy_decision == POLICY_FALLBACK_DETERMINISTIC
    assert receipt.curation_mode == DETERMINISTIC
    assert body["curation_mode"] == DETERMINISTIC
    # Protected facts restored from before
    assert body["protected_facts"]["price"] == 190.25
    assert body["protected_facts"]["price"] != 999.99
    # Rejected LLM body must not be the delivered sanitized_body
    assert body["sanitized_body"] != curated
    assert receipt.provider == "grok"
    assert receipt.model == "grok-4"
    assert receipt.protected_facts_before_hash != receipt.protected_facts_after_hash


def test_receipt_store_roundtrip():
    ev = _approval_event()
    ev.mint_identity()
    _, receipt = curate_deterministic(ev)
    store_curation_receipt(ev.event_id, receipt)
    got = get_curation_receipt(ev.event_id)
    assert got is not None
    assert got.event_id == ev.event_id
    assert got.curation_mode == DETERMINISTIC
    assert got.to_dict()["fact_preservation_ok"] is True


def test_llm_denied_for_tier0_approval_class():
    ev = _approval_event()
    ev.mint_identity()
    body, receipt = apply_llm_curation_result(
        event=ev,
        curated_body="LLM rewrite of approval",
        protected_facts_after=dict(ev.protected_facts),
        provider="chatgpt",
        model="gpt-5",
        requested_mode=LLM_SUMMARY,
    )
    assert body["curation_mode"] == DETERMINISTIC
    assert receipt.curation_mode == DETERMINISTIC
    assert receipt.fact_preservation_ok is True
    assert body["protected_facts"]["quantity"] == 10
