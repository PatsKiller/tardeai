#!/usr/bin/env python3
"""Unit tests for Subject Memory / SubjectThread@v1."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.client import (  # noqa: E402
    publish_communication,
    reset_memory_store,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.comms.subject_memory import (  # noqa: E402
    attach_event_to_subject,
    get_subject,
    memory_subject_snapshot,
    reset_subject_memory,
    retrieve_subject_history,
    subject_key_for,
    upsert_subject,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    reset_memory_store()
    reset_subject_memory()
    yield
    reset_memory_store()
    reset_subject_memory()


def test_subject_key_deterministic_shorthand():
    a = subject_key_for("symbol", symbol="aapl")
    b = subject_key_for("symbol", symbol="AAPL")
    assert a == b == "symbol:AAPL"
    assert subject_key_for("system", component="watchdog") == "system:watchdog"
    assert subject_key_for("account", account_id="acct_1") == "account:acct_1"
    assert subject_key_for("incident", incident_id="inc_9") == "incident:inc_9"
    assert subject_key_for("proposal", proposal_id="p1") == "proposal:p1"
    assert subject_key_for("research", research_id="ri_1") == "research:ri_1"
    assert subject_key_for("operator", topic="approvals") == "operator:approvals"


def test_subject_key_multi_part_sorted():
    k1 = subject_key_for("incident", incident_id="inc1", account_id="a2")
    k2 = subject_key_for("incident", account_id="a2", incident_id="inc1")
    assert k1 == k2
    assert k1 == "incident:account_id=a2:incident_id=inc1"


def test_subject_key_rejects_bad_domain():
    with pytest.raises(ValueError, match="invalid subject domain"):
        subject_key_for("broker", id="x")
    with pytest.raises(ValueError, match="at least one"):
        subject_key_for("symbol")


def test_upsert_and_attach_memory_fallback():
    sk = subject_key_for("symbol", symbol="MSFT")
    sub = upsert_subject(
        sk,
        domain="symbol",
        canonical_entities={"symbol": "MSFT"},
        latest_state={"status": "watching"},
    )
    assert sub["subject_key"] == sk
    assert sub["persisted"] == "memory"
    assert get_subject(sk)["latest_state"]["status"] == "watching"

    m = attach_event_to_subject(sk, "evt_1", channel="telegram", provider_coordinates={"chat_id": 1})
    assert m["event_id"] == "evt_1"
    assert m["persisted"] == "memory"
    # Idempotent
    m2 = attach_event_to_subject(sk, "evt_1", channel="telegram")
    assert m2["event_id"] == "evt_1"
    snap = memory_subject_snapshot()
    assert len(snap["membership"]) == 1


def test_retrieve_attach_and_eligible_only_filter():
    sk = subject_key_for("system", component="watchdog")

    eligible = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key=sk,
        retention_class="ops_7d",
        sanitized_body="watchdog ok",
        channels=["telegram"],
        knowledge_eligibility="eligible",
    )
    ineligible = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health_debug",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key=sk,
        retention_class="ops_7d",
        sanitized_body="debug noise",
        channels=["slack"],
        knowledge_eligibility="ineligible",
        observation_version="debug",
    )
    summary_ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health_digest",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key=sk,
        retention_class="ops_7d",
        short_summary="digest of watchdog",
        sanitized_body=None,
        channels=["email"],
        knowledge_eligibility="eligible",
        curation_mode="LLM_SUMMARY",
        observation_version="digest",
    )

    r1 = publish_communication(eligible)
    r2 = publish_communication(ineligible)
    r3 = publish_communication(summary_ev)
    assert r1.ok and r2.ok and r3.ok

    hist_all = retrieve_subject_history(sk, limit=50, eligible_only=False)
    ids_all = {h["event_id"] for h in hist_all}
    assert r1.event_id in ids_all
    assert r2.event_id in ids_all
    assert r3.event_id in ids_all

    hist = retrieve_subject_history(sk, limit=50, eligible_only=True)
    ids = {h["event_id"] for h in hist}
    assert r1.event_id in ids
    assert r3.event_id in ids
    assert r2.event_id not in ids

    kinds = {h["event_id"]: h["artifact_kind"] for h in hist}
    assert kinds[r1.event_id] == "evidence"
    assert kinds[r3.event_id] == "summary"

    # Cross-channel membership recorded via publish hook
    channels = {h["event_id"]: h.get("channel") for h in hist_all}
    assert channels[r1.event_id] == "telegram"
    assert channels[r2.event_id] == "slack"


def test_memory_fallback_without_db():
    """Subject memory works with in-process store when DB tables are absent."""
    sk = subject_key_for("operator", topic="cutover")
    upsert_subject(sk, open_questions=["when is ACTIVE?"])
    attach_event_to_subject(sk, "evt_mem_only", channel="telegram")

    # eligible_only skips membership stubs without eligibility proof
    assert retrieve_subject_history(sk, eligible_only=True) == []

    hist = retrieve_subject_history(sk, eligible_only=False)
    assert len(hist) == 1
    assert hist[0]["event_id"] == "evt_mem_only"
    assert hist[0]["artifact_kind"] == "evidence"
    assert hist[0]["source"] == "memory_membership"
    assert get_subject(sk)["open_questions"] == ["when is ACTIVE?"]
