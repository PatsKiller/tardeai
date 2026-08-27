"""R20 V2 Lane C — notification_id determinism + record() idempotency.

notification_id is ntf_ + digest(lineage, material_generation_id, class)
with no wall-clock. Same generation+class does not mint a second identity
or a second audit row. SUPPRESSED replay keeps the same id.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_notification_signal import (  # noqa: E402
    DELIVERY_IMMEDIATE,
    DELIVERY_SUPPRESSED,
    NotificationStateStore,
    decide_notification,
    material_generation_id,
)

pytestmark = pytest.mark.tier0


@pytest.fixture
def store(tmp_path: Path) -> NotificationStateStore:
    return NotificationStateStore(
        state_path=tmp_path / "state.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        metrics_path=tmp_path / "metrics.jsonl",
    )


def _deploy_cash(*, digest: str = "gen-a") -> dict:
    return {
        "decision_id": f"dec_cash_{digest}",
        "symbol": "CASH",
        "action": "DEPLOY_CASH",
        "stance_code": "DEPLOY_CASH",
        "standing_recommendation": "DEPLOY_CASH",
        "current_action": "DEPLOY_CASH",
        "act_now": True,
        "actionability": "ACT_NOW",
        "delta_usd": 50000.0,
        "why_now": "Deploy cash.",
        "cash_posture": {"cash_posture_status": "ABOVE_BAND"},
        "cash_posture_status": "ABOVE_BAND",
        "capital": {"free_investable": 322000, "deploy_now": 50000, "remain_cash": 256000},
        "decision_evidence_digest": digest,
        "environment": "PROD",
        "synthetic": False,
    }


def _hold_cash(*, digest: str = "gen-hold", status: str = "ABOVE_BAND") -> dict:
    return {
        "decision_id": f"dec_cash_{digest}",
        "symbol": "CASH",
        "action": "HOLD_CASH",
        "stance_code": "HOLD_CASH",
        "standing_recommendation": "HOLD_CASH",
        "current_action": "HOLD_CASH",
        "act_now": False,
        "actionability": "NO_ACTION",
        "delta_usd": 0.0,
        "why_now": f"Cash {status}; hold.",
        "cash_posture": {"cash_posture_status": status},
        "cash_posture_status": status,
        "capital": {"free_investable": 322000, "deploy_now": 0, "remain_cash": 256000},
        "decision_evidence_digest": digest,
        "environment": "PROD",
        "synthetic": False,
    }


def _audit_rows(store: NotificationStateStore) -> list[dict]:
    path = store.audit_path
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def test_same_generation_class_twice_one_id_not_two_audit_rows(store: NotificationStateStore) -> None:
    decision = _deploy_cash()
    nd1 = decide_notification(decision, store=store)
    nd2 = decide_notification(decision, store=store)
    assert nd1["notification_class"] == nd2["notification_class"] == DELIVERY_IMMEDIATE
    assert nd1["material_generation_id"] == nd2["material_generation_id"]
    assert nd1["notification_id"] == nd2["notification_id"]
    assert nd1["notification_id"].startswith("ntf_")
    store.record(nd1)
    store.record(nd2)
    rows = _audit_rows(store)
    assert len(rows) == 1
    assert rows[0]["notification_id"] == nd1["notification_id"]


def test_record_same_object_twice_updates_index_only(store: NotificationStateStore) -> None:
    nd = decide_notification(_deploy_cash(), store=store)
    store.record(nd)
    first_updated = store.latest(nd["decision_lineage_id"])["updated_at"]
    time.sleep(0.01)
    store.record(nd)
    latest = store.latest(nd["decision_lineage_id"])
    assert latest["notification_id"] == nd["notification_id"]
    assert latest["material_generation_id"] == nd["material_generation_id"]
    assert latest["notification_class"] == nd["notification_class"]
    assert latest["updated_at"] >= first_updated
    assert len(_audit_rows(store)) == 1


def test_suppressed_replay_remains_suppressed_same_id(store: NotificationStateStore) -> None:
    first = _deploy_cash(digest="same-gen")
    nd1 = decide_notification(first, store=store)
    store.record(nd1)
    assert nd1["notification_class"] == DELIVERY_IMMEDIATE
    replay = _deploy_cash(digest="same-gen-evidence-churn")
    assert material_generation_id(first) == material_generation_id(replay)
    nd2 = decide_notification(replay, store=store)
    store.record(nd2)
    assert nd2["notification_class"] == DELIVERY_SUPPRESSED
    assert nd2["suppressed_reason"]
    assert nd2["notification_id"] == nd1["notification_id"]
    # Second record is a different class, so one extra audit row is allowed;
    # a third identical SUPPRESSED record must not grow the audit again.
    store.record(nd2)
    ids = {row["notification_id"] for row in _audit_rows(store)}
    assert ids == {nd1["notification_id"]}
    suppressed_rows = [
        row for row in _audit_rows(store) if row.get("notification_class") == DELIVERY_SUPPRESSED
    ]
    assert len(suppressed_rows) == 1


def test_changed_material_generation_new_notification_id(store: NotificationStateStore) -> None:
    hold = _hold_cash(digest="g1", status="ABOVE_BAND")
    nd1 = decide_notification(hold, store=store)
    store.record(nd1)
    deploy = _deploy_cash(digest="g2")
    nd2 = decide_notification(deploy, store=store)
    store.record(nd2)
    assert material_generation_id(hold) != material_generation_id(deploy)
    assert nd1["material_generation_id"] != nd2["material_generation_id"]
    assert nd1["notification_id"] != nd2["notification_id"]
    assert nd2["notification_class"] == DELIVERY_IMMEDIATE


def test_hundred_identical_decide_record_loops_one_id(store: NotificationStateStore) -> None:
    decision = _deploy_cash(digest="loop-gen")
    generation = material_generation_id(decision)
    ids: set[str] = set()
    for _ in range(100):
        nd = decide_notification(decision, store=store)
        store.record(nd)
        assert nd["material_generation_id"] == generation
        ids.add(nd["notification_id"])
    assert len(ids) == 1
    unique_audit_ids = {
        row["notification_id"]
        for row in _audit_rows(store)
        if row.get("material_generation_id") == generation
    }
    assert unique_audit_ids == ids
    latest = store.latest(nd["decision_lineage_id"])
    assert latest["notification_id"] in ids


def test_notification_id_ignores_wall_clock(store: NotificationStateStore) -> None:
    decision = _deploy_cash(digest="clock")
    nd1 = decide_notification(decision, store=store)
    time.sleep(0.02)
    nd2 = decide_notification(decision, store=store)
    assert nd1["notification_id"] == nd2["notification_id"]
    assert nd1["notification_id"].startswith("ntf_")
    assert nd1["created_at"] != nd1["notification_id"]
    assert nd1["created_at"] not in nd1["notification_id"]


def test_notification_id_has_no_iso_timestamp_fragment(store: NotificationStateStore) -> None:
    nd = decide_notification(_deploy_cash(), store=store)
    nid = nd["notification_id"]
    created = nd["created_at"]
    assert created[:10] not in nid
    assert ":" not in nid
    assert nid.startswith("ntf_")


def test_restart_reload_resumes_same_durable_checkpoint(tmp_path: Path) -> None:
    """A new store on the same files must not mint a second identity."""
    paths = dict(
        state_path=tmp_path / "state.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        metrics_path=tmp_path / "metrics.jsonl",
    )
    first = NotificationStateStore(**paths)
    nd1 = decide_notification(_deploy_cash(digest="reload-gen"), store=first)
    first.record(nd1)
    restarted = NotificationStateStore(**paths)
    nd2 = decide_notification(_deploy_cash(digest="reload-gen"), store=restarted)
    restarted.record(nd2)
    assert nd2["notification_id"] == nd1["notification_id"]
    assert nd2["notification_class"] == DELIVERY_SUPPRESSED
    rows = [
        json.loads(line)
        for line in paths["audit_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["notification_id"] for row in rows} == {nd1["notification_id"]}


def test_failed_processing_does_not_advance_checkpoint(store: NotificationStateStore) -> None:
    """decide() without record() must not persist a cursor."""
    decision = _deploy_cash(digest="fail-gen")
    nd = decide_notification(decision, store=store)
    assert store.latest(nd["decision_lineage_id"]) is None
    assert _audit_rows(store) == []


def test_older_generation_after_newer_is_material_change_not_regression(
    store: NotificationStateStore,
) -> None:
    """Older digest after newer is a material change, not a cursor rollback.

    The durable index keeps the last recorded decision; it does not lose the
    lineage or rewind to empty. A new semantic id is allowed because the
    material generation changed.
    """
    newer = decide_notification(_deploy_cash(digest="gen-new"), store=store)
    store.record(newer)
    older = decide_notification(_hold_cash(digest="gen-old"), store=store)
    store.record(older)
    assert older["notification_id"] != newer["notification_id"]
    latest = store.latest(newer["decision_lineage_id"])
    assert latest is not None
    assert latest["notification_id"] == older["notification_id"]
    assert latest["material_generation_id"] == older["material_generation_id"]
