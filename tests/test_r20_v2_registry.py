"""Control-plane domains are registry-backed; first-AVAILABLE does not steal wrong stores."""
from __future__ import annotations

import json
from pathlib import Path

import scripts.control_plane_api as api


INTENDED = (
    "system",
    "agents",
    "workflows",
    "research",
    "stores",
    "identity",
    "notifications",
    "learning",
    "maturity",
    "audit",
)


def test_all_intended_domains_are_registry_mapped() -> None:
    assert tuple(api.CONTROL_PLANE_DOMAINS) == INTENDED
    for name, spec in api.CONTROL_PLANE_DOMAINS.items():
        assert "store_ids" in spec
        assert "fallbacks" in spec
        if spec.get("kind") != "computed":
            assert spec["store_ids"] or spec["fallbacks"]


def test_operator_product_does_not_steal_workflows(tmp_path: Path, monkeypatch) -> None:
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "cio_operator_product.jsonl").write_text(
        json.dumps({"product_id": "p1", "generation_id": "g1", "material": True}) + "\n"
    )
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/workflows")
    assert status == 200
    assert body["data_quality"] == "UNAVAILABLE"
    assert body["data"]["items"] == []


def test_research_projection_dict_does_not_empty_steal(tmp_path: Path, monkeypatch) -> None:
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "hermes_research_projection.json").write_text(json.dumps({"updated_ts": "now"}))
    (cio / "hermes_research_requests.jsonl").write_text(
        json.dumps({"research_id": "res_1", "plan_id": "plan_1", "status": "queued"}) + "\n"
    )
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/research")
    assert status == 200
    assert body["data_quality"] == "AVAILABLE"
    assert body["data"]["items"][0]["research_id"] == "res_1"


def test_empty_valid_list_is_available(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent_registry.json").write_text("[]")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200
    assert body["data_quality"] == "AVAILABLE"
    assert body["data"]["pagination"]["total"] == 0


def test_notifications_prefer_audit_then_outbox(tmp_path: Path, monkeypatch) -> None:
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "cio_notification_audit.jsonl").write_text(
        json.dumps({"notification_id": "ntf_audit", "notification_class": "SUPPRESSED"}) + "\n"
    )
    (cio / "cio_notification_outbox.jsonl").write_text(
        json.dumps({"notification_id": "ntf_outbox"}) + "\n"
    )
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    _, body = api.handle("/api/v3/control-plane/notifications")
    assert body["data_quality"] == "AVAILABLE"
    assert body["data"]["items"][0]["notification_id"] == "ntf_audit"


def test_system_uses_expected_idle_taxonomy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/system")
    assert status == 200
    hermes = body["data"]["queues"][0]
    assert hermes["state"] in {
        "EXPECTED_IDLE",
        "QUEUE_WAITING",
        "ON_DEMAND_READY",
        "EVENT_DRIVEN_IDLE",
        "SCHEDULED",
        "UNKNOWN",
        "FAILED",
        "DISABLED",
        "DEGRADED",
        "ON_DEMAND_RUNNING",
        "QUEUE_ACTIVE",
    }
    assert hermes["state"] != "BROKEN"
    assert body["data"]["authority"] == "READ_ONLY_ADVISORY"
