#!/usr/bin/env python3
"""Phase 7 — communications_portal list/empty/health projections."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.client import (  # noqa: E402
    memory_store_snapshot,
    publish_communication,
    reset_memory_store,
)
from scripts.lib.comms.delivery import reset_memory_deliveries  # noqa: E402
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.comms.subject_memory import reset_subject_memory  # noqa: E402

import communications_portal as portal  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    # Hermetic: force memory/empty path even when a live DSN is present.
    monkeypatch.setattr(portal, "_events_db_conn", lambda: None)
    monkeypatch.setattr(portal, "_deliveries_db_conn", lambda: None)
    monkeypatch.setattr(portal, "_subjects_db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    reset_memory_store()
    reset_memory_deliveries()
    reset_subject_memory()
    yield
    reset_memory_store()
    reset_memory_deliveries()
    reset_subject_memory()


def _sample_event(**kwargs) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="pipeline_stale",
        message_class="ops_alert",
        producer="ops.health",
        subject_key="system:pipeline",
        retention_class="operational_30d",
        severity="warning",
        audience="operator",
        sanitized_body="pipeline stale",
        short_summary="pipeline stale",
        channels=["telegram"],
    )
    base.update(kwargs)
    return CommunicationEvent(**base)


def test_health_empty_ledger_delivery_not_owned():
    h = portal.health()
    assert h["ok"] is True
    assert h["delivery_owned"] is False
    assert h["owned_classes"] == []
    assert h["mode"] == "OFF"
    assert "ledger" in h
    assert h["ledger"]["source"] in ("empty", "memory", "db")
    assert "OFF/SHADOW" in h["banner"] or "does not own delivery" in h["banner"]


def test_health_active_ops_reports_delivery_owned(monkeypatch):
    """ACTIVE + allowlist must not lie with delivery_owned=false."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.setenv("COMMS_GATEWAY_ACTIVE_CLASSES", "ops")
    h = portal.health()
    assert h["ok"] is True
    assert h["mode"] == "ACTIVE"
    assert h["delivery_owned"] is True
    assert h["owned_classes"] == ["ops"]
    assert "ops" in h["banner"]
    assert "OFF/SHADOW" not in h["banner"]


def test_health_active_empty_allowlist_fail_closed(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    monkeypatch.delenv("COMMS_GATEWAY_ACTIVE_CLASSES", raising=False)
    h = portal.health()
    assert h["mode"] == "ACTIVE"
    assert h["delivery_owned"] is False
    assert h["owned_classes"] == []
    assert "fail-closed" in h["banner"] or "allowlist" in h["banner"]


def test_list_events_empty_honest_source():
    out = portal.list_events(limit=10)
    assert out["ok"] is True
    assert out["events"] == []
    assert out["total"] == 0
    assert out["source"] in ("empty", "db")  # db empty or no mem


def test_list_events_from_memory_after_publish():
    result = publish_communication(_sample_event())
    assert result.ok and result.event_id
    assert result.event_id in memory_store_snapshot()

    out = portal.list_events(limit=50)
    assert out["ok"] is True
    assert out["source"] == "memory"
    assert out["total"] >= 1
    row = next(e for e in out["events"] if e["event_id"] == result.event_id)
    assert row["event_type"] == "pipeline_stale"
    assert row["subject_key"] == "system:pipeline"
    assert row["producer"] == "ops.health"
    assert row["severity"] == "warning"
    assert row["curation_mode"]
    assert row["created_at"]


def test_list_events_subject_filter():
    publish_communication(_sample_event(subject_key="system:pipeline", observation_version="1"))
    publish_communication(
        _sample_event(
            subject_key="symbol:RKLB",
            event_type="symbol_alert",
            observation_version="1",
        )
    )
    out = portal.list_events(limit=50, subject_key="symbol:RKLB")
    assert out["source"] == "memory"
    assert all(e["subject_key"] == "symbol:RKLB" for e in out["events"])
    assert len(out["events"]) >= 1


def test_get_event_memory_and_missing():
    result = publish_communication(_sample_event(observation_version="get1"))
    got = portal.get_event(result.event_id)
    assert got["ok"] is True
    assert got["source"] == "memory"
    assert got["event"]["event_id"] == result.event_id

    missing = portal.get_event("does-not-exist")
    assert missing["ok"] is False
    assert missing["event"] is None
    assert missing["source"] == "empty"


def test_list_deliveries_and_subjects_after_publish():
    result = publish_communication(_sample_event(observation_version="dlv1"))
    assert result.ok

    dlv = portal.list_deliveries(event_id=result.event_id)
    assert dlv["ok"] is True
    # Phase 3 auto-reserves telegram stub into memory
    assert dlv["source"] in ("memory", "empty", "db")
    if dlv["deliveries"]:
        assert all(d.get("event_id") == result.event_id for d in dlv["deliveries"])

    subs = portal.list_subjects(limit=20)
    assert subs["ok"] is True
    assert subs["source"] in ("memory", "empty", "db")
    if subs["subjects"]:
        keys = {s["subject_key"] for s in subs["subjects"]}
        assert "system:pipeline" in keys


def test_portal_never_imports_providers():
    """Guard: communications_portal must not pull telegram/slack senders."""
    src = Path(portal.__file__).read_text(encoding="utf-8")
    lowered = src.lower()
    for forbidden in (
        "telegram_bot",
        "send_telegram",
        "slack_sdk",
        "from telegram",
        "import telegram",
        "slack_webhook",
    ):
        assert forbidden not in lowered
