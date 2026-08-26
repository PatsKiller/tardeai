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
