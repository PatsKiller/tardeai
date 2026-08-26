"""R22 — ControlPlane@v1.0.0 fixture envelopes and mock copies."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.control_plane_contract_v1 import (
    RUNTIME_STATUS,
    SCHEMA,
    WORKFLOW_NODE_KINDS,
    load_fixture,
    validate_envelope,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "control_plane" / "v1.0.0"
MOCK_DIR = ROOT / "apps/command-center-v3/src/pages/control-plane/r22/mocks"


def test_agents_fixture_envelope_validates():
    doc = load_fixture("agents")
    assert validate_envelope(doc) == []
    assert doc["schema"] == SCHEMA
    assert doc["page"] == "agents"
    assert doc["authority"] == "READ_ONLY_ADVISORY"
    assert doc["memory_behavior_influence"] == 0
    assert doc["computes_cio_decisions"] is False
    assert doc["computes_agent_state"] is False
    assert doc["computes_maturity"] is False
    assert doc["computes_notification_eligibility"] is False
    assert doc["financial_action"] is False


def test_workflows_fixture_envelope_validates():
    doc = load_fixture("workflows")
    assert validate_envelope(doc) == []
    assert doc["schema"] == SCHEMA
    assert doc["page"] == "workflows"
    assert doc["computes_cio_decisions"] is False
    assert doc["computes_maturity"] is False
    assert doc["computes_notification_eligibility"] is False


def test_agents_fixture_covers_every_runtime_status():
    states = [a["state"] for a in load_fixture("agents")["payload"]["agents"]]
    assert set(states) >= set(RUNTIME_STATUS)
    for status in RUNTIME_STATUS:
        assert status in states


def test_workflows_fixture_nodes_are_full_lineage_in_order():
    traces = load_fixture("workflows")["payload"]["traces"]
    assert traces
    kinds = [n["kind"] for n in traces[0]["nodes"]]
    assert kinds == list(WORKFLOW_NODE_KINDS)


def test_mock_copies_match_fixture_semantics():
    for name in ("agents", "workflows"):
        fixture = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
        mock = json.loads((MOCK_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert mock == fixture
        assert validate_envelope(mock) == []


def test_remaining_mocks_are_listed_and_labeled_fixture():
    manifest_path = ROOT / "docs/_evidence/r22/REMAINING_MOCKS.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["http_freeze"] == "CONTROL_PLANE_API_V1_BASELINE"
    remaining = manifest["remaining"]
    paths = []
    for row in remaining:
        blob = json.dumps(row)
        assert "FIXTURE" in blob
        assert row["path"].startswith("apps/command-center-v3/src/pages/control-plane/r22/mocks/")
        path = ROOT / row["path"]
        assert path.is_file(), row["path"]
        paths.append(row["path"])
        assert "not production" in row.get("label", "").lower() or "FIXTURE/MOCK" in row.get("label", "")
    assert "apps/command-center-v3/src/pages/control-plane/r22/mocks/agents.json" in paths
    assert "apps/command-center-v3/src/pages/control-plane/r22/mocks/workflows.json" in paths
