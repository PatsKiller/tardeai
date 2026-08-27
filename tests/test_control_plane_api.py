from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.control_plane_api as api


def test_all_routes_are_get_projection():
    for route in api.ROUTES:
        status, body = api.handle(route, method="GET")
        assert status == 200
        assert {"as_of", "source_sha", "freshness", "data_quality", "evidence_class", "data"}.issubset(body)


def test_post_is_rejected_without_mutation():
    status, body = api.handle("/api/v3/control-plane/system", method="POST")
    assert status == 405
    assert body["data"]["error"] == "control-plane is read-only"


def test_pagination_is_bounded_and_stable(tmp_path, monkeypatch):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    target = tmp_path / "data" / "runtime" / "agent_registry.json"
    target.write_text(json.dumps([{"agent_id": str(i)} for i in range(4)]))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents", query={"limit": "2", "offset": "1"})
    assert status == 200
    assert body["data"]["items"] == [{"agent_id": "1"}, {"agent_id": "2"}]
    assert body["data"]["pagination"]["total"] == 4


def test_missing_store_is_explicit_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/stores")
    assert status == 200
    assert body["data_quality"] == "UNAVAILABLE"
    assert body["data"]["items"] == []


def test_invalid_json_is_explicit_invalid_schema(tmp_path, monkeypatch):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "data" / "runtime" / "agent_registry.json").write_text("not-json")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200
    assert body["data_quality"] == "INVALID_SCHEMA"


def test_non_control_plane_path_returns_none():
    assert api.handle("/api/v3/advisory") is None


def test_canonical_jsonl_projection_is_visible(tmp_path, monkeypatch):
    """Control-plane readers consume canonical append-only production stores."""
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "cio_notification_outbox.jsonl").write_text(
        json.dumps({"notification_id": "n1", "decision_id": "d1", "status": "SUPPRESSED"}) + "\n"
    )
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/notifications")
    assert status == 200
    assert body["data_quality"] == "AVAILABLE"
    assert body["data"]["items"][0]["notification_id"] == "n1"


def test_canonical_watchlist_path_is_not_retired_root():
    source = Path("scripts/lib/cio_desk_synthesis.py").read_text()
    assert '"data" / "portfolios" / "state" / "watchlist.json"' in source
    assert '"data" / "watchlist" / "state" / "watchlist.json"' not in source


def test_agent_detail_and_unknown_states(tmp_path, monkeypatch):
    root = tmp_path / "data" / "runtime"; root.mkdir(parents=True)
    (root / "agent_registry.json").write_text(json.dumps([{
        "agent_id": "hermes", "role": "research", "runtime_state": "EXPECTED_IDLE",
        "recent_artifacts": [{"id": "a1"}, {"id": "a2"}], "evidence_class": "SHADOW"
    }]))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents/hermes", query={"limit": "1"})
    assert status == 200 and body["data"]["runtime_state"] == "EXPECTED_IDLE"
    assert body["data"]["recent_artifacts"]["pagination"]["total"] == 2
    _, unknown = api.handle("/api/v3/control-plane/agents/nope")
    assert unknown["data"]["status"] == "UNKNOWN_AGENT"


def test_workflow_cross_id_partial_and_cutoff(tmp_path, monkeypatch):
    root = tmp_path / "data" / "runtime"; root.mkdir(parents=True)
    payload = [{"workflow_id": "w1", "decision_id": "d1", "generation_id": "g1",
                "nodes": [{"id": "e", "node_type": "source_event", "timestamp": "2026-01-01T00:00:00Z"},
                          {"id": "c", "node_type": "cio_product", "timestamp": "2026-01-02T00:00:00Z"}],
                "edges": [{"from": "e", "to": "missing", "relationship": "TRIGGERED"}]}]
    (root / "workflow_traces.json").write_text(json.dumps(payload))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/workflows/d1")
    assert status == 200 and body["data"]["workflow_id"] == "w1"
    assert len(body["data"]["nodes"]) == 2
    assert body["data"]["unresolved_links"]
    _, cutoff = api.handle("/api/v3/control-plane/workflows/w1", query={"until": "2026-01-01T12:00:00Z"})
    assert len(cutoff["data"]["nodes"]) == 1


def test_append_only_lineage_records_are_grouped_for_detail(tmp_path, monkeypatch):
    cio = tmp_path / "data" / "cio"; cio.mkdir(parents=True)
    records = [
        {"record_type": "node", "workflow_id": "wf1", "node_type": "RESEARCH", "node_id": "r1", "as_of": "2026-01-01T00:00:00Z"},
        {"record_type": "node", "workflow_id": "wf1", "node_type": "CHECKPOINT", "node_id": "cp1", "as_of": "2026-01-02T00:00:00Z"},
        {"record_type": "edge", "workflow_id": "wf1", "from": "r1", "to": "cp1", "relationship": "CHECKPOINTED_BY"},
    ]
    (cio / "cio_workflow_lineage.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/workflows/r1")
    assert status == 200
    assert body["data"]["workflow_id"] == "wf1"
    assert {n["node_id"] for n in body["data"]["nodes"]} == {"r1", "cp1"}
    assert body["data"]["edges"][0]["relationship"] == "CHECKPOINTED_BY"
