#!/usr/bin/env python3
"""Unit tests for Phase 6 Librarian retention decisions."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.comms.identity import new_event_id  # noqa: E402
from scripts.lib.comms.librarian import (  # noqa: E402
    ACCEPTED,
    CANDIDATE,
    COMPACT,
    DELETE_CONTENT_KEEP_TOMBSTONE,
    HOLD,
    KEEP,
    REJECTED,
    RetentionDecision,
    apply_retention_decision,
    classify_retention,
    decide_knowledge_candidate,
    execute_expiry_pass,
    get_knowledge_candidate,
    get_tombstone,
    propose_knowledge_candidate,
    reset_librarian_memory,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_librarian_memory()
    yield
    reset_librarian_memory()


def _event(**kwargs) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="ops_ping",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="operational_30d",
        channels=["telegram"],
        sanitized_body="ping",
        event_id=new_event_id(),
    )
    base.update(kwargs)
    return CommunicationEvent(**base)


def test_classify_operational_30d():
    ev = _event(retention_class="operational_30d")
    d = classify_retention(ev)
    assert isinstance(d, RetentionDecision)
    assert d.action == DELETE_CONTENT_KEEP_TOMBSTONE
    assert d.content_ttl_seconds == 30 * 86400
    assert d.expires_at is not None
    assert d.legal_hold is False
    assert d.policy_version == "RetentionDecision@v1"


def test_classify_inbound_7d_and_ops_7d():
    inbound = classify_retention(_event(retention_class="inbound_7d", direction="INBOUND"))
    assert inbound.action == DELETE_CONTENT_KEEP_TOMBSTONE
    assert inbound.content_ttl_seconds == 7 * 86400

    ops = classify_retention(_event(retention_class="ops_7d"))
    assert ops.content_ttl_seconds == 7 * 86400


def test_classify_approval_ttl_keeps():
    d = classify_retention(_event(retention_class="approval_ttl", message_class="approval"))
    assert d.action == KEEP
    assert d.content_ttl_seconds == 365 * 86400


def test_classify_research_365d_compacts():
    d = classify_retention(_event(retention_class="research_365d", message_class="research"))
    assert d.action == COMPACT
    assert d.content_ttl_seconds == 365 * 86400


def test_classify_dict_event_like():
    d = classify_retention(
        {
            "event_id": "evt_dict_1",
            "retention_class": "operational_30d",
            "message_class": "operator_alert",
        }
    )
    assert d.event_id == "evt_dict_1"
    assert d.action == DELETE_CONTENT_KEEP_TOMBSTONE


def test_legal_hold_forces_hold_and_blocks_delete():
    ev = _event(retention_class="ops_7d", legal_hold=True)
    d = classify_retention(ev)
    assert d.action == HOLD
    assert d.legal_hold is True
    assert d.expires_at is None

    applied = apply_retention_decision(d)
    assert applied.persisted == "memory"

    # Force an expired non-hold-looking row would be skipped; hold decision itself
    # is never executable even if we forge expires_at.
    applied.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    # Re-store forged expiry under same decision_id for expiry pass scan.
    apply_retention_decision(applied)

    report = execute_expiry_pass(dry_run=False)
    assert report["executed"] == 0
    # Hold rows are filtered before execute; if somehow present, blocked.
    for r in report["results"]:
        assert r.get("executed") is False
    assert get_tombstone(ev.event_id) is None


def test_expiry_pass_dry_run_default_no_tombstone():
    ev = _event(retention_class="inbound_7d")
    d = classify_retention(ev)
    # Expire immediately.
    d.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    apply_retention_decision(d)

    report = execute_expiry_pass()  # dry_run defaults True
    assert report["dry_run"] is True
    assert report["examined"] >= 1
    assert report["would_execute"] >= 1
    assert report["executed"] == 0
    assert get_tombstone(ev.event_id) is None

    report2 = execute_expiry_pass(dry_run=False)
    assert report2["executed"] >= 1
    ts = get_tombstone(ev.event_id)
    assert ts is not None
    assert ts["action"] == DELETE_CONTENT_KEEP_TOMBSTONE


def test_keep_action_not_purged_on_expiry():
    ev = _event(retention_class="approval_ttl")
    d = classify_retention(ev)
    assert d.action == KEEP
    d.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    apply_retention_decision(d)

    report = execute_expiry_pass(dry_run=False)
    blocked = [r for r in report["results"] if r["event_id"] == ev.event_id]
    assert blocked
    assert blocked[0]["blocked"] is True
    assert blocked[0]["reason"] == "keep_not_executable"
    assert get_tombstone(ev.event_id) is None


def test_knowledge_candidate_requires_owner_and_provenance():
    with pytest.raises(ValueError, match="owner required"):
        propose_knowledge_candidate(
            "evt_1",
            "AAPL is oversold",
            owner="",
            evidence_refs=[{"uri": "note:1"}],
        )
    with pytest.raises(ValueError, match="provenance"):
        propose_knowledge_candidate(
            "evt_1",
            "AAPL is oversold",
            owner="hermes.research",
            evidence_refs=None,
        )
    with pytest.raises(ValueError, match="provenance"):
        propose_knowledge_candidate(
            "evt_1",
            "AAPL is oversold",
            owner="hermes.research",
            evidence_refs=[],
        )


def test_knowledge_candidate_no_auto_accept():
    row = propose_knowledge_candidate(
        "evt_research_1",
        "Thesis: AAPL pullback into support",
        owner="hermes.research",
        evidence_refs=[{"source_type": "research", "uri": "artifact:1"}],
        review_path="/v3/knowledge/review",
    )
    assert row["status"] == CANDIDATE
    assert row["status"] != ACCEPTED
    assert get_knowledge_candidate(row["candidate_id"])["status"] == CANDIDATE

    # Explicit review required for ACCEPTED.
    decided = decide_knowledge_candidate(
        row["candidate_id"],
        ACCEPTED,
        reviewer="operator.john",
    )
    assert decided["status"] == ACCEPTED
    assert decided["reviewer"] == "operator.john"
    assert decided["decided_at"] is not None


def test_decide_rejects_without_reviewer_and_invalid_status():
    row = propose_knowledge_candidate(
        "evt_2",
        "assertion",
        owner="ops",
        evidence_refs=[{"uri": "e:1"}],
    )
    with pytest.raises(ValueError, match="reviewer required"):
        decide_knowledge_candidate(row["candidate_id"], REJECTED, reviewer="")
    with pytest.raises(ValueError, match="status_invalid"):
        decide_knowledge_candidate(row["candidate_id"], CANDIDATE, reviewer="op")


def test_apply_retention_from_event_like():
    ev = _event(retention_class="ops_7d")
    d = apply_retention_decision(event_like=ev)
    assert d.persisted == "memory"
    assert d.decision_id.startswith("rtd_")
    assert d.action == DELETE_CONTENT_KEEP_TOMBSTONE
