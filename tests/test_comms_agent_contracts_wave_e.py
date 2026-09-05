#!/usr/bin/env python3
"""Unit tests for Wave E persistent-agent subscriptions (agent_contracts.py).

Covers the subscription read API (policy-eligible events only, expired and
unauthorized content excluded), AgentConsumptionReceipt recording (version +
influence lineage), and the no-self-adjudication / knowledge-status gate.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.agent_contracts import (  # noqa: E402
    AgentContractError,
    assert_no_truth_claim_without_knowledge_gate,
    eligible_events_for_agent,
    emit_consumption_receipt,
    event_is_verified_fact,
    event_policy_eligibility,
    get_consumption_receipt,
    list_consumption_receipts,
    register_subscription,
    reset_agent_contracts_memory,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    # Same defect shape as tests/test_comms_delivery_ledger.py: every call site
    # is `conn = _db_conn(); if conn is not None: <db> else: <memory>`, and on a
    # box where localhost Postgres answers the DB branch wins. Force no DB so
    # tests assert the in-memory ledger and never touch production Postgres.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.agent_contracts._db_conn", lambda: None)
    reset_agent_contracts_memory()
    yield
    reset_agent_contracts_memory()


def _event(
    event_id: str,
    *,
    message_class: str = "research",
    subject_key: str = "research:alpha",
    knowledge_eligibility: str = "eligible",
    knowledge_status: str = "none",
    expires_at=None,
) -> dict:
    return {
        "event_id": event_id,
        "message_class": message_class,
        "severity": "info",
        "subject_key": subject_key,
        "knowledge_eligibility": knowledge_eligibility,
        "knowledge_status": knowledge_status,
        "expires_at": expires_at,
    }


def _register(agent_id: str, *, classes=None, domains=None) -> None:
    register_subscription(
        agent_id,
        agent_version="1.0.0",
        filter={"message_classes": classes or [], "subject_domains": domains or []},
    )


def test_subscription_returns_only_eligible_events():
    _register("cio", classes=["research"])
    _register("hermes", classes=["research"])
    events = [
        _event("evt_a", subject_key="research:alpha"),
        _event("evt_b", message_class="ops", subject_key="system:watchdog"),
        _event("evt_c", subject_key="research:gamma"),
    ]
    got = eligible_events_for_agent("cio", events)
    assert {e["event_id"] for e in got} == {"evt_a", "evt_c"}
    # Advisory has no subscription yet -> empty, not a blanket allow.
    assert eligible_events_for_agent("advisory", events) == []


def test_expired_content_excluded():
    _register("cio", classes=["research"])
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    events = [
        _event("evt_expired", expires_at=past),
        _event("evt_live", expires_at=future),
        _event("evt_no_expiry", expires_at=None),
    ]
    got = eligible_events_for_agent("cio", events, eligible_only=True)
    assert {e["event_id"] for e in got} == {"evt_live", "evt_no_expiry"}
    # Raw (unfiltered) view still shows the expired row for debugging.
    raw = eligible_events_for_agent("cio", events, eligible_only=False)
    assert {e["event_id"] for e in raw} == {"evt_expired", "evt_live", "evt_no_expiry"}


def test_unauthorized_content_excluded():
    _register("cio", classes=["research"])
    events = [
        _event("evt_blocked", knowledge_eligibility="blocked"),
        _event("evt_retracted", knowledge_status="retracted"),
        _event("evt_hypothesis", knowledge_eligibility="eligible", knowledge_status="none"),
        _event("evt_accepted", knowledge_eligibility="eligible", knowledge_status="accepted"),
    ]
    # A Hermes hypothesis (knowledge_status "none") is policy-eligible for
    # retrieval/context, but not a verified fact — it is NOT excluded here.
    got = eligible_events_for_agent("cio", events, eligible_only=True)
    assert {e["event_id"] for e in got} == {"evt_hypothesis", "evt_accepted"}
    # Policy verdicts are explicit and legible.
    assert event_policy_eligibility(events[0]) == (False, "unauthorized_knowledge_status")
    assert event_policy_eligibility(events[2]) == (True, "eligible")


def test_consumption_receipt_records_version_and_influence():
    receipt = emit_consumption_receipt(
        "cio",
        event_id="evt_a",
        purpose="informed_advisory",
        agent_version="2.1.3",
        derived_artifact_ids=["adv_1", "adv_2"],
        influence_declaration="hypothesis used in recommendation, not fact",
        influence_event_ids=["evt_a"],
    )
    assert receipt.receipt_id and receipt.receipt_id.startswith("acr_")
    assert receipt.retrieved_at is not None
    row = get_consumption_receipt(receipt.receipt_id)
    assert row is not None
    assert row["agent_id"] == "cio"
    assert row["agent_version"] == "2.1.3"
    assert row["event_id"] == "evt_a"
    assert row["derived_artifact_ids"] == ["adv_1", "adv_2"]
    assert row["influence_declaration"] == "hypothesis used in recommendation, not fact"
    assert row["influence_event_ids"] == ["evt_a"]


def test_self_adjudication_rejected():
    # An agent may never stamp institutional truth onto a consumed event.
    with pytest.raises(AgentContractError) as ei:
        emit_consumption_receipt("hermes", event_id="evt_h", purpose="used", knowledge_status="ACCEPTED")
    assert "self_certification_rejected" in str(ei.value)

    # Knowledge-status gate: claiming a non-gated hypothesis as truth is rejected.
    hypothesis = _event("evt_h", knowledge_eligibility="eligible", knowledge_status="none")
    with pytest.raises(AgentContractError) as ei2:
        assert_no_truth_claim_without_knowledge_gate(hypothesis, claimed_status="TRUTH", agent_id="hermes")
    assert "truth_claim_rejected_without_knowledge_gate" in str(ei2.value)

    # A Librarian-gated (ACCEPTED) event IS a verified fact, so the gate allows it.
    verified = _event("evt_v", knowledge_eligibility="eligible", knowledge_status="accepted")
    assert event_is_verified_fact(verified) is True
    assert event_is_verified_fact(hypothesis) is False
    assert_no_truth_claim_without_knowledge_gate(verified, claimed_status="TRUTH")

    # ...but even a verified event cannot be re-stamped by the consuming agent
    # (the unconditional self-certification ban still applies).
    with pytest.raises(AgentContractError) as ei3:
        emit_consumption_receipt(
            "hermes",
            event_id="evt_v",
            purpose="used",
            event=verified,
            knowledge_status="ACCEPTED",
        )
    assert "self_certification_rejected" in str(ei3.value)

    # Emitting a truth claim on a non-gated event via the receipt path is
    # rejected by the knowledge gate before the self-cert check.
    with pytest.raises(AgentContractError) as ei4:
        emit_consumption_receipt(
            "hermes",
            event_id="evt_h",
            purpose="used",
            event=hypothesis,
            claimed_knowledge_status="TRUTH",
        )
    assert "truth_claim_rejected_without_knowledge_gate" in str(ei4.value)


def test_list_consumption_receipts_and_filter_by_agent():
    r1 = emit_consumption_receipt("cio", event_id="evt_a", purpose="informed_advisory")
    r2 = emit_consumption_receipt("hermes", event_id="evt_b", purpose="research")
    r3 = emit_consumption_receipt("cio", event_id="evt_c", purpose="decision")

    all_receipts = list_consumption_receipts()
    ids = {r["receipt_id"] for r in all_receipts}
    assert r1.receipt_id in ids and r2.receipt_id in ids and r3.receipt_id in ids

    cio_only = list_consumption_receipts("cio")
    assert all(r["agent_id"] == "cio" for r in cio_only)
    assert len(cio_only) == 2

    # Unknown agent filter yields empty, not a blanket allow.
    assert list_consumption_receipts("nobody") == []


def test_portal_agent_consumption_projection():
    from scripts.communications_portal import list_agent_consumption

    emit_consumption_receipt(
        "advisory",
        event_id="evt_d",
        purpose="recommendation",
        agent_version="1.0",
        derived_artifact_ids=["adv_1"],
        influence_declaration="hypothesis used, not fact",
    )
    payload = list_agent_consumption()
    assert payload["ok"] is True
    assert payload["total_receipts"] >= 1
    rec = next(r for r in payload["receipts"] if r["event_id"] == "evt_d")
    assert rec["agent_id"] == "advisory"
    assert rec["derived_artifact_ids"] == ["adv_1"]
    assert rec["influence_declaration"] == "hypothesis used, not fact"
    assert "subscriptions" in payload
