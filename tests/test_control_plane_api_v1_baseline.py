"""Pin CONTROL_PLANE_API_V1_BASELINE (084674c5 summary envelope).

R21.1 detail/lineage may add routes. This test forbids renaming the frozen
summary envelope keys or collection shape.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.control_plane_api as api

BASELINE = json.loads(
    (Path(__file__).resolve().parents[1] / "docs" / "convergence" / "CONTROL_PLANE_API_V1_BASELINE.json").read_text()
)
ENVELOPE = set(BASELINE["envelope_required"])
COLLECTION = set(BASELINE["collection_data_required"])
PAGINATION = set(BASELINE["pagination_required"])
SUMMARY = tuple(BASELINE["summary_routes"])


def test_frozen_summary_routes_match_module():
    assert tuple(api.ROUTES) == SUMMARY


def test_summary_envelope_keys_are_frozen():
    for route in SUMMARY:
        status, body = api.handle(route, method="GET")
        assert status == 200
        assert ENVELOPE.issubset(body)
        assert "payload" not in body


def test_collection_shape_except_system():
    for route in SUMMARY:
        if route.endswith("/system"):
            continue
        _, body = api.handle(route, method="GET")
        assert COLLECTION.issubset(body["data"])
        assert PAGINATION.issubset(body["data"]["pagination"])


def test_system_projects_advisory_not_live():
    _, body = api.handle("/api/v3/control-plane/system")
    data = body["data"]
    assert data["authority"] == "READ_ONLY_ADVISORY"
    assert data["memory_behavior_influence"] == 0
    assert data["runtime"]["state"] != "LIVE"
    assert data["runtime"]["state"] != "LIVE_EVENT_DRIVEN"


def test_mutations_stay_405():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        status, body = api.handle("/api/v3/control-plane/agents", method=method)
        assert status == 405
        assert body["data"]["error"] == "control-plane is read-only"
