#!/usr/bin/env python3
"""Unit tests for Phase 8 agent consumption contracts / AgentConsumptionReceipt@v1."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.agent_contracts import (  # noqa: E402
    KNOWN_AGENTS,
    SCHEMA_VERSION,
    AgentConsumptionReceipt,
    AgentContractError,
    acknowledge_consumption,
    assert_not_self_certifying_truth,
    declare_influence,
    eligible_events_for_agent,
    emit_consumption_receipt,
    get_consumption_receipt,
    list_subscriptions,
    memory_agent_contracts_snapshot,
    register_subscription,
    reset_agent_contracts_memory,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Same defect as the other comms suites: these assert the in-memory ledger,
    # and on a box where localhost Postgres answers the DB branch wins — the
    # assertions fail and the run writes to production. agent_contracts carries
    # its own _db_conn (:91), separate from client/delivery/subject_memory/librarian.
    monkeypatch.setattr("scripts.lib.comms.agent_contracts._db_conn", lambda: None)
    reset_agent_contracts_memory()
    yield
    reset_agent_contracts_memory()


def test_known_agents_set():
    assert KNOWN_AGENTS == frozenset({"cio", "hermes", "advisory", "darwin", "maria"})
    assert SCHEMA_VERSION == "AgentConsumptionReceipt@v1"


def test_subscribe_and_filter_eligible_events():
    sub = register_subscription(
        "hermes",
        agent_version="1.0.0",
        filter={
            "message_classes": ["research", "research_brief"],
            "severities": ["info", "warning"],
            "subject_domains": ["symbol", "research"],
        },
    )
    assert sub["subscription_id"].startswith("sub_")
    assert sub["agent_id"] == "hermes"
    assert sub["persisted"] == "memory"
    assert sub["filter"]["message_classes"] == ["research", "research_brief"]

    listed = list_subscriptions("hermes")
    assert len(listed) == 1
    assert listed[0]["subscription_id"] == sub["subscription_id"]

    events = [
        {
            "event_id": "e1",
            "message_class": "research",
            "severity": "info",
            "subject_key": "symbol:AAPL",
        },
        {
            "event_id": "e2",
            "message_class": "approval",
            "severity": "critical",
            "subject_key": "approval:order:1",
        },
        {
            "event_id": "e3",
            "message_class": "research_brief",
            "severity": "warning",
            "subject_key": "research:ri_1",
        },
        {
            "event_id": "e4",
            "message_class": "research",
            "severity": "info",
            "subject_key": "account:acct_1",
        },
    ]
    eligible = eligible_events_for_agent("hermes", events)
    ids = {e["event_id"] for e in eligible}
    assert ids == {"e1", "e3"}


def test_empty_filter_matches_all_when_subscribed():
    register_subscription("cio", agent_version="2.0", filter=None)
    events = [
        {"event_id": "a", "message_class": "health", "severity": "info", "subject_key": "system:x"},
        {"event_id": "b", "message_class": "research", "severity": "warning", "subject_key": "symbol:X"},
    ]
    eligible = eligible_events_for_agent("cio", events)
    assert {e["event_id"] for e in eligible} == {"a", "b"}


def test_no_subscription_yields_no_eligible():
    events = [{"event_id": "z", "message_class": "research", "severity": "info", "subject_key": "symbol:Z"}]
    assert eligible_events_for_agent("maria", events) == []


def test_receipt_emit_and_acknowledge():
    receipt = emit_consumption_receipt(
        "darwin",
        event_id="evt_42",
        purpose="decision_context",
        agent_version="0.3",
        thread_id="thr_symbol:MSFT",
        artifact_ids=["art_1"],
        policy_decision="allow",
    )
    assert isinstance(receipt, AgentConsumptionReceipt)
    assert receipt.receipt_id.startswith("acr_")
    assert receipt.agent_id == "darwin"
    assert receipt.event_id == "evt_42"
    assert receipt.purpose == "decision_context"
    assert receipt.acknowledged_at is None
    assert receipt.persisted == "memory"

    loaded = get_consumption_receipt(receipt.receipt_id)
    assert loaded is not None
    assert loaded["event_id"] == "evt_42"

    ack = acknowledge_consumption(receipt.receipt_id)
    assert ack["acknowledged_at"] is not None
    assert get_consumption_receipt(receipt.receipt_id)["acknowledged_at"] is not None


def test_influence_declaration():
    receipt = emit_consumption_receipt(
        "advisory",
        event_id="evt_inf",
        purpose="advisory_draft",
        agent_version="1.1",
    )
    row = declare_influence(
        receipt.receipt_id,
        "Used as prior for SCHD trim advisory",
        influence_event_ids=["evt_inf", "evt_prior_1"],
    )
    assert row["influence_declaration"] == "Used as prior for SCHD trim advisory"
    assert row["influence_event_ids"] == ["evt_inf", "evt_prior_1"]

    # Can also emit with influence inline
    r2 = emit_consumption_receipt(
        "advisory",
        event_id="evt_inf2",
        purpose="sizing_context",
        influence_declaration="Influenced sizing note",
        influence_event_ids=["evt_inf2"],
    )
    assert r2.influence_declaration == "Influenced sizing note"


def test_self_certification_rejected_on_emit():
    with pytest.raises(AgentContractError, match="self_certification_rejected"):
        emit_consumption_receipt(
            "cio",
            event_id="evt_bad",
            purpose="truth_claim",
            knowledge_status="ACCEPTED",
        )
    with pytest.raises(AgentContractError, match="self_certification_rejected"):
        emit_consumption_receipt(
            "hermes",
            event_id="evt_bad2",
            purpose="truth_claim",
            claimed_knowledge_status="canonical",
        )
    snap = memory_agent_contracts_snapshot()
    assert snap["receipts"] == {}


def test_assert_not_self_certifying_truth():
    assert_not_self_certifying_truth("cio", None)
    assert_not_self_certifying_truth("cio", "")
    assert_not_self_certifying_truth("cio", "none")
    assert_not_self_certifying_truth("cio", "retrieved")
    with pytest.raises(AgentContractError, match="self_certification_rejected"):
        assert_not_self_certifying_truth("maria", "ACCEPTED")
    with pytest.raises(AgentContractError, match="self_certification_rejected"):
        assert_not_self_certifying_truth("maria", "AUTHORITATIVE")


def test_unknown_agent_rejected_by_default():
    with pytest.raises(AgentContractError, match="unknown agent_id"):
        register_subscription("nova", agent_version="1.0")
    with pytest.raises(AgentContractError, match="unknown agent_id"):
        emit_consumption_receipt("nova", event_id="e", purpose="x")
    with pytest.raises(AgentContractError, match="unknown agent_id"):
        eligible_events_for_agent("nova", [])


def test_unknown_agent_allowed_with_flag():
    sub = register_subscription(
        "nova",
        agent_version="0.1",
        filter={"message_classes": ["ops_summary"]},
        allow_unknown=True,
    )
    assert sub["agent_id"] == "nova"
    events = [
        {
            "event_id": "n1",
            "message_class": "ops_summary",
            "severity": "info",
            "subject_key": "system:nova",
        }
    ]
    eligible = eligible_events_for_agent("nova", events, allow_unknown=True)
    assert len(eligible) == 1
    receipt = emit_consumption_receipt(
        "nova",
        event_id="n1",
        purpose="future_agent_pilot",
        allow_unknown=True,
    )
    assert receipt.agent_id == "nova"


def test_emit_requires_purpose_and_event():
    with pytest.raises(AgentContractError, match="event_id"):
        emit_consumption_receipt("cio", event_id="", purpose="x")
    with pytest.raises(AgentContractError, match="purpose"):
        emit_consumption_receipt("cio", event_id="e1", purpose="  ")


def test_package_exports():
    from scripts.lib.comms import (
        AgentConsumptionReceipt as ExpReceipt,
        AgentContractError as ExpErr,
        KNOWN_AGENTS as ExpKnown,
        acknowledge_consumption as exp_ack,
        assert_not_self_certifying_truth as exp_assert,
        declare_influence as exp_decl,
        eligible_events_for_agent as exp_elig,
        emit_consumption_receipt as exp_emit,
        register_subscription as exp_reg,
    )

    assert ExpKnown is KNOWN_AGENTS
    assert ExpReceipt is AgentConsumptionReceipt
    assert ExpErr is AgentContractError
    assert callable(exp_reg)
    assert callable(exp_emit)
    assert callable(exp_ack)
    assert callable(exp_decl)
    assert callable(exp_elig)
    assert callable(exp_assert)
