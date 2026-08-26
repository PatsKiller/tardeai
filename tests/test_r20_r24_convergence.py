"""R20-R24 cross-stream proof: R21.1, dry-run IDs, replay, temporal, faults, authority, secrets."""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.control_plane_api as api

DRY = ROOT / "fixtures/control_plane/dry_run"
REPLAY = ROOT / "fixtures/control_plane/replay"
IDS = json.loads((DRY / "IDS.json").read_text())["ids"]
ENVELOPE = {"ok", "as_of", "source_sha", "freshness", "data_quality", "evidence_class", "data"}
SECRET_RE = re.compile(
    r"(?ix)(api[_-]?key|secret_key|private[_-]?key|passwd|password|telegram_bot_token|BEGIN (RSA |OPENSSH )?PRIVATE)"
)
CROSS_KEYS = [
    "workflow_id", "event_id", "decision_id", "generation_id", "artifact_id",
    "notification_id", "checkpoint_id", "outcome_id", "research_id", "council_id",
]


@pytest.fixture
def dry_root(monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", DRY)
    return DRY


def test_summary_envelope_keys_frozen(dry_root):
    for route in api.ROUTES:
        status, body = api.handle(route)
        assert status == 200
        assert ENVELOPE.issubset(body)
        assert "payload" not in body


def test_detail_uses_same_outer_envelope(dry_root):
    _, body = api.handle("/api/v3/control-plane/agents/maria")
    assert ENVELOPE.issubset(body)
    assert body["data"]["runtime_state"] == "LIVE_EVENT_DRIVEN"
    assert body["data"]["evidence_class"] == "DRY_RUN"
    _, idle = api.handle("/api/v3/control-plane/agents/ledger")
    assert idle["data"]["runtime_state"] == "EXPECTED_IDLE"
    _, broken = api.handle("/api/v3/control-plane/agents/aegis")
    assert broken["data"]["runtime_state"] == "BROKEN"
    _, callable_only = api.handle("/api/v3/control-plane/agents/vega")
    assert callable_only["data"]["runtime_state"] == "CALLABLE_ONLY"
    _, disabled = api.handle("/api/v3/control-plane/agents/pulse")
    assert disabled["data"]["runtime_state"] == "DISABLED"


def test_cross_id_resolves_same_workflow(dry_root):
    _, canonical = api.handle(f"/api/v3/control-plane/workflows/{IDS['workflow_id']}")
    assert canonical["data"]["workflow_id"] == IDS["workflow_id"]
    assert canonical["data"]["evidence_class"] == "DRY_RUN"
    node_types = [n["node_type"] for n in canonical["data"]["nodes"]]
    for required in ("SOURCE_EVENT", "ENTITY", "MATERIALITY", "RESEARCH_GAP", "FREE_FIRST", "SPECIALIST_DISPATCH", "SPECIALIST_ARTIFACT", "COUNCIL", "CIO_PRODUCT", "NOTIFICATION", "CHECKPOINT", "OUTCOME", "LEARNING"):
        assert required in node_types
    for key in CROSS_KEYS:
        _, body = api.handle(f"/api/v3/control-plane/workflows/{IDS[key]}")
        assert body["data"]["workflow_id"] == IDS["workflow_id"]
        assert body["data"]["identifiers"]["event_id"] == IDS["event_id"]
        assert body["data"]["identifiers"]["decision_id"] == IDS["decision_id"]
        assert body["data"]["identifiers"]["generation_id"] == IDS["generation_id"]
        assert body["data"]["source_sha"] == canonical["data"]["source_sha"]
        assert body["data"]["evidence_class"] == canonical["data"]["evidence_class"]
        assert [n["node_id"] for n in body["data"]["nodes"]] == [n["node_id"] for n in canonical["data"]["nodes"]]


def test_same_ids_across_summary_pages(dry_root):
    _, research = api.handle("/api/v3/control-plane/research")
    _, identity = api.handle("/api/v3/control-plane/identity")
    _, notes = api.handle("/api/v3/control-plane/notifications")
    _, learning = api.handle("/api/v3/control-plane/learning")
    subjects = [row.get("subject_id") or row.get("entity_id") for row in research["data"]["items"]]
    assert IDS["entity_guid"] in subjects
    assert any(row.get("entity_id") == IDS["entity_guid"] for row in identity["data"]["items"])
    assert any(row.get("notification_id") == IDS["notification_id"] for row in notes["data"]["items"])
    assert any(row.get("workflow_id") == IDS["workflow_id"] for row in learning["data"]["items"])
    assert all(row.get("status") != "promoted" for row in learning["data"]["items"])


def test_temporal_cutoff_hides_later_nodes(dry_root):
    _, full = api.handle(f"/api/v3/control-plane/workflows/{IDS['workflow_id']}")
    _, cut = api.handle(f"/api/v3/control-plane/workflows/{IDS['workflow_id']}", query={"until": "2026-08-26T12:05:00Z"})
    full_types = [n["node_type"] for n in full["data"]["nodes"]]
    cut_types = [n["node_type"] for n in cut["data"]["nodes"]]
    assert "NOTIFICATION" in full_types
    assert "CHECKPOINT" in full_types
    assert "OUTCOME" in full_types
    assert "LEARNING" in full_types
    assert "NOTIFICATION" not in cut_types
    assert "CHECKPOINT" not in cut_types
    assert "OUTCOME" not in cut_types
    assert "LEARNING" not in cut_types


def test_partial_lineage_is_explicit(dry_root):
    _, body = api.handle("/api/v3/control-plane/workflows/partial.workflow.001")
    certs = {e["certainty"] for e in body["data"]["edges"]}
    assert "MISSING_PARENT" in certs
    assert "LEGACY_REFERENCE" in certs
    assert "UNAVAILABLE_STORE" in certs
    assert "QUARANTINED_RECORD" in certs
    assert "UNRESOLVED_LINK" in certs
    assert body["data_quality"] == "PARTIAL"
    node_ids = {n["node_id"] for n in body["data"]["nodes"]}
    assert "ghost" not in node_ids
    assert "missing_parent" not in node_ids


def test_historical_replay_count_and_no_lookahead(monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", REPLAY)
    _, listing = api.handle("/api/v3/control-plane/workflows", query={"limit": "200"})
    assert listing["data"]["pagination"]["total"] == 120
    leaks = 0
    for i in range(120):
        wid = f"replay.workflow.{i:03d}"
        _, full = api.handle(f"/api/v3/control-plane/workflows/{wid}")
        assert full["data"]["evidence_class"] == "HISTORICAL_REPLAY"
        cutoff = full["data"]["nodes"][0]["timestamp"]
        _, cut = api.handle(f"/api/v3/control-plane/workflows/{wid}", query={"as_of": cutoff})
        later = {n["node_type"] for n in cut["data"]["nodes"]}
        if "NOTIFICATION" in later or "OUTCOME" in later or "LEARNING" in later:
            leaks += 1
    assert leaks == 0


def test_fault_campaign_typed_degradation(tmp_path, monkeypatch):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    _, missing = api.handle("/api/v3/control-plane/research")
    assert missing["data_quality"] == "UNAVAILABLE"
    (runtime / "agent_registry.json").write_text("not-json")
    _, invalid = api.handle("/api/v3/control-plane/agents")
    assert invalid["data_quality"] == "INVALID_SCHEMA"
    (runtime / "workflow_traces.json").write_text(json.dumps([{
        "workflow_id": "stale.cio", "data_quality": "STALE",
        "evidence_class": "DRY_RUN",
        "nodes": [{"id": "c", "node_type": "cio_product", "timestamp": "2026-01-01T00:00:00Z"}],
        "edges": [],
    }]))
    _, stale = api.handle("/api/v3/control-plane/workflows/stale.cio")
    assert stale["data_quality"] == "STALE"
    _, unknown = api.handle("/api/v3/control-plane/agents/nope")
    assert unknown["data"]["status"] == "UNKNOWN_AGENT"


def test_mutations_405_on_summary_and_detail(dry_root):
    routes = list(api.ROUTES) + [
        "/api/v3/control-plane/agents/maria",
        f"/api/v3/control-plane/workflows/{IDS['workflow_id']}",
    ]
    violations = []
    for route in routes:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            status, body = api.handle(route, method=method)
            if status != 405:
                violations.append((route, method, status))
            assert body["data"]["error"] == "control-plane is read-only"
    assert violations == []


def test_secret_scan_freeze_and_fixtures():
    hits = []
    targets = [
        ROOT / "scripts/control_plane_api.py",
        ROOT / "fixtures/control_plane",
        ROOT / "apps/command-center-v3/src/pages/control-plane",
        ROOT / "docs/_evidence/r20-r24",
        ROOT / "docs/convergence",
    ]
    for target in targets:
        paths = [target] if target.is_file() else list(target.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() in {".png", ".jpg", ".pdf", ".woff", ".woff2"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if SECRET_RE.search(text):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_runtime_mocks_are_not_page_truth():
    office = (ROOT / "apps/command-center-v3/src/pages/control-plane/r22/AgentOfficePage.tsx").read_text()
    trace = (ROOT / "apps/command-center-v3/src/pages/control-plane/r22/WorkflowTracePage.tsx").read_text()
    assert "agentDetailUrl" in office
    assert "/api/v3/control-plane/agents/" in office
    assert 'data-testid="agent-detail-fixture"' not in office
    assert "workflowDetailUrl" in trace
    assert "/api/v3/control-plane/workflows/" in trace
    assert "data-role=\"TEST_FIXTURE\"" in office
    assert "data-role=\"TEST_FIXTURE\"" in trace
    for stream in ("r23", "r24"):
        src = "\n".join(
            p.read_text()
            for p in (ROOT / "apps/command-center-v3/src/pages/control-plane" / stream).rglob("*")
            if p.suffix in {".ts", ".tsx"}
        )
        assert "/api/v3/control-plane/" in src


def test_shadow_routes_registered_without_cutover():
    app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text()
    for path in (
        "control-plane", "control-plane/system", "control-plane/agents", "control-plane/workflows",
        "control-plane/research", "control-plane/data", "control-plane/identity",
        "control-plane/notifications", "control-plane/learning", "control-plane/maturity",
        "control-plane/audit",
    ):
        assert f'path="{path}"' in app
    assert 'path="agents"' in app
    assert 'path="research-intelligence"' in app
    assert 'path="system"' in app
    assert 'Navigate to="/control-plane' not in app


def test_system_is_not_live_claim(dry_root):
    _, body = api.handle("/api/v3/control-plane/system")
    assert body["data"]["authority"] == "READ_ONLY_ADVISORY"
    assert body["data"]["memory_behavior_influence"] == 0
    assert body["data"]["runtime"]["state"] not in {"LIVE", "LIVE_EVENT_DRIVEN", "LIVE_SCHEDULED"}
