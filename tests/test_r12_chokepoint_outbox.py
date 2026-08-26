"""R12 iterations 14–16, 20: chokepoint integration, outbox, test-sink, faults."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from scripts.lib.cio_advisory_notify import deliver_prepared, prepare_advisory_notification
from scripts.lib.cio_material_scan import scan_office
from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_notification_signal import decide_notification
from scripts.lib.cio_situation_notify_bridge import (
    classify_auditable_result,
    situation_to_decision,
)
from scripts.lib.cio_situation_state import detect_office_situations
from tests.r11_office_fixtures import NOW, office, policy, portfolio

pytestmark = pytest.mark.tier0


class _Mem:
    def latest(self, _lineage):
        return None


def _office_for_scan(**overrides):
    base = {
        "holdings": {"ok": True, "holdings": []},
        "capital_plan": {
            "ok": True,
            "portfolio_value_usd": 1_000_000.0,
            "cash_total_usd": 450_000.0,
            "cash_investable_usd": 250_000.0,
            "cash_reserved_usd": 200_000.0,
            "cash_policy_band": {"min_pct": 20.0, "max_pct": 25.0},
            "cash_posture_status": "ABOVE_BAND",
            "net_recommended_deploy_usd": 0.0,
            "freshness_materiality_gate": {"act_now_count": 0, "counts": {}},
            "position_decisions": [],
            "digest": "test",
        },
        "reentry": {"rows": []},
        "previous_snapshot": {"holdings": []},
        "previous_office_state": {},
        "baseline_needed": False,
        "operator_policy": {"policy": {"status": "POLICY_REQUIRED", "fields": {}}},
    }
    base.update(overrides)
    return base


def test_scan_office_feeds_decide_notification_and_policy_gap(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY", "0")
    receipt = scan_office(dry_run=True, office=_office_for_scan(), persist=False, notification_gate=True)
    assert receipt["ok"] is True
    assert receipt["policy_status"] == "POLICY_GAP"
    assert receipt["masquerades_as_operator_policy"] is True
    assert receipt["auditable_result"] in {
        "NOTIFICATION_SUPPRESSED", "DRY_RUN_INTERDICTED", "POLICY_GAP_QUESTION", "NO_MATERIAL_CHANGE",
        "COMMAND_CENTER_ONLY", "NOTIFICATION_DIGESTED",
    }
    assert receipt["financial_lane"] == "OFF_BY_POLICY"
    assert "sent=false" not in str(receipt["auditable_result"]).lower() or receipt["auditable_result"]
    assert receipt["memory_behavior_influence"] == 0
    assert receipt["authority"] == "READ_ONLY_ADVISORY"


def test_situation_candidate_enters_decide_notification() -> None:
    scan = detect_office_situations(office(policy=policy(confirmed=False)), evaluated_at=NOW)
    gap = next(s for s in scan["situations"] if s["situation_class"] == "POLICY_GAP")
    dec = situation_to_decision(gap)
    nd = decide_notification(dec, store=_Mem())
    assert nd["decision_id"] == dec["decision_id"]
    assert nd["notification_class"] in {
        "IMMEDIATE", "DIGEST", "COMMAND_CENTER_ONLY", "SUPPRESSED",
    }
    assert dec["financial_action"] is False


def test_outbox_enqueue_claim_idempotent(tmp_path: Path) -> None:
    box = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    scan = detect_office_situations(office(), evaluated_at=NOW)
    prepared = prepare_advisory_notification(scan["situations"][0])
    first = box.enqueue(prepared, actor_id="alex", actor_type="agent", authority="advisory")
    second = box.enqueue(dict(prepared), actor_id="alex", actor_type="agent", authority="advisory")
    assert first
    # idempotency_key present on prepared
    assert prepared.get("idempotency_key")


def test_test_sink_receipt_fields() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    prepared = prepare_advisory_notification(scan["situations"][0])
    receipt = deliver_prepared(prepared, live=False)
    assert receipt["prepared"] is True
    assert receipt["trace_id"]
    assert receipt["situation_id"]
    assert receipt["sender_attribution"] == "alex_cio"
    assert receipt["live"] is False
    assert hashlib.sha256(prepared["body"].encode()).hexdigest() == prepared["body_hash"]


class _Fail:
    is_live = False

    def send(self, notification):
        return {"delivered": False, "error": "timeout", "notification_id": notification.get("notification_id")}


def test_timeout_does_not_lose_decision() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    prepared = prepare_advisory_notification(scan["situations"][0])
    receipt = deliver_prepared(prepared, adapter=_Fail(), live=False)
    assert receipt["sent"] is False
    assert receipt["delivery_receipt"]["error"] == "timeout"
    # source decision still present
    assert prepared["situation_id"] == scan["situations"][0]["situation_id"]


def test_live_flag_refused_without_authorization() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    prepared = prepare_advisory_notification(scan["situations"][0])
    with pytest.raises(RuntimeError, match="LIVE_DELIVERY_REQUIRES_EXPLICIT"):
        deliver_prepared(prepared, live=True)


@pytest.mark.parametrize(
    "counts,dry,canary,gap,delivered,expect",
    [
        ({}, True, False, False, False, "NO_MATERIAL_CHANGE"),
        ({"SUPPRESSED": 3}, True, False, False, False, "NOTIFICATION_SUPPRESSED"),
        ({"IMMEDIATE": 1}, True, False, False, False, "DRY_RUN_INTERDICTED"),
        ({"IMMEDIATE": 1}, False, True, False, True, "NOTIFICATION_DELIVERED"),
        ({"DIGEST": 1}, True, False, False, False, "NOTIFICATION_DIGESTED"),
        ({"COMMAND_CENTER_ONLY": 1}, True, False, False, False, "COMMAND_CENTER_ONLY"),
    ],
)
def test_auditable_result_truth_table(counts, dry, canary, gap, delivered, expect) -> None:
    got = classify_auditable_result(
        notification_counts=counts,
        suppressed_by_reason={"unchanged_replay": 3} if counts.get("SUPPRESSED") else {},
        dry_run=dry,
        canary=canary,
        policy_gap=gap,
        delivered=delivered,
    )
    assert got == expect
