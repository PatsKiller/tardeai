#!/usr/bin/env python3
"""Unit tests for Wave D Librarian purge receipts (PurgeReceipt@v1)."""
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
    DELETE_CONTENT_KEEP_TOMBSTONE,
    HOLD,
    KEEP,
    REDACT,
    apply_retention_decision,
    execute_expiry_pass,
    get_purge_receipt,
    get_tombstone,
    list_purge_receipts,
    record_purge_receipt,
    reset_librarian_memory,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # librarian.py carries its own _db_conn (separate from client/delivery/
    # subject_memory). Stub it to None so these tests exercise the in-memory
    # stores and never touch production Postgres — the same defect pattern
    # documented in tests/test_comms_delivery_ledger.py and
    # tests/test_comms_librarian.py.
    monkeypatch.setattr("scripts.lib.comms.librarian._db_conn", lambda: None)
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


def test_purge_execution_writes_receipt_with_hashes_and_tombstone():
    ev = _event(retention_class="inbound_7d", sanitized_body="secret payload")
    d = apply_retention_decision(event_like=ev)
    assert ev.content_hash  # minted during classify
    # Expire immediately, then re-store the forged expiry.
    d.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    apply_retention_decision(d)

    report = execute_expiry_pass(dry_run=False)
    assert report["executed"] >= 1

    receipts = [
        r
        for r in list_purge_receipts()
        if r["action"] == DELETE_CONTENT_KEEP_TOMBSTONE and r["tombstone"] is True
    ]
    assert receipts
    r = receipts[0]
    assert r["decision_id"] == d.decision_id
    assert r["retention_class"] == "inbound_7d"
    assert r["event_ids"] == [ev.event_id]
    assert r["content_hashes"] == [ev.content_hash]
    assert r["tombstone"] is True
    assert r["decided_by"]
    assert r["policy_version"] == "RetentionDecision@v1"
    assert r["decided_at"] is not None


def test_dry_run_writes_would_delete_receipt_and_deletes_nothing():
    ev = _event(retention_class="ops_7d", sanitized_body="to be purged")
    d = apply_retention_decision(event_like=ev)
    d.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    apply_retention_decision(d)

    report = execute_expiry_pass(dry_run=True)
    assert report["dry_run"] is True
    assert report["executed"] == 0
    assert report["would_execute"] >= 1
    assert get_tombstone(ev.event_id) is None

    receipts = [r for r in list_purge_receipts() if r["decision_id"] == d.decision_id]
    would_delete = [r for r in receipts if r["dry_run"] is True]
    assert would_delete
    r = would_delete[0]
    assert r["note"] == "would-delete (dry-run)"
    assert r["tombstone"] is False
    assert r["action"] == DELETE_CONTENT_KEEP_TOMBSTONE
    assert r["event_ids"] == [ev.event_id]
    assert ev.content_hash in r["content_hashes"]
    # Nothing was actually deleted.
    assert get_tombstone(ev.event_id) is None


def test_hold_blocks_purge_and_records_hold():
    ev = _event(retention_class="ops_7d", legal_hold=True)
    d = apply_retention_decision(event_like=ev)
    assert d.action == HOLD

    report = execute_expiry_pass(dry_run=False)
    assert report["executed"] == 0
    assert get_tombstone(ev.event_id) is None

    hold_receipts = [r for r in list_purge_receipts() if r["action"] == HOLD]
    assert hold_receipts
    r = hold_receipts[-1]
    assert r["tombstone"] is False
    assert r["decision_id"] == d.decision_id
    assert r["event_ids"] == [ev.event_id]
    assert r["note"] == "hold: retention suspended; deletes blocked"


def test_record_purge_receipt_schema_fields():
    decided = datetime.now(timezone.utc)
    r = record_purge_receipt(
        decision_id="rtd_direct",
        action=REDACT,
        retention_class="research_365d",
        event_ids="evt_a",
        artifact_ids=["art_1", "art_2"],
        content_hashes="abc123",
        tombstone=True,
        decided_by="comms.librarian",
        policy_version="RetentionDecision@v1",
        decided_at=decided,
        dry_run=False,
        note="redaction executed",
    )
    assert r["receipt_id"].startswith("pr_")
    assert r["schema"] == "PurgeReceipt@v1"
    assert r["decision_id"] == "rtd_direct"
    assert r["action"] == REDACT
    assert r["retention_class"] == "research_365d"
    assert r["event_ids"] == ["evt_a"]
    assert r["artifact_ids"] == ["art_1", "art_2"]
    assert r["content_hashes"] == ["abc123"]
    assert r["tombstone"] is True
    assert r["decided_by"] == "comms.librarian"
    assert r["policy_version"] == "RetentionDecision@v1"
    assert r["decided_at"] == decided
    assert get_purge_receipt(r["receipt_id"])["receipt_id"] == r["receipt_id"]


def test_record_purge_receipt_requires_action():
    with pytest.raises(ValueError, match="action required"):
        record_purge_receipt(decision_id="x", action="", retention_class="c")


def test_keep_not_purged_records_keep_receipt():
    ev = _event(retention_class="approval_ttl")
    d = apply_retention_decision(event_like=ev)
    assert d.action == KEEP
    d.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    apply_retention_decision(d)

    report = execute_expiry_pass(dry_run=False)
    assert report["executed"] == 0
    assert get_tombstone(ev.event_id) is None

    keep = [r for r in list_purge_receipts() if r["action"] == KEEP]
    assert keep
    assert keep[-1]["tombstone"] is False
    assert keep[-1]["event_ids"] == [ev.event_id]
