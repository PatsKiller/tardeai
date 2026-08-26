"""Local-sync gate proofs: pages, routes, replay class, stores, parity, performance."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.control_plane_api as api

APP = (ROOT / "apps/command-center-v3/src/App.tsx").read_text()
NAV = (ROOT / "apps/command-center-v3/src/components/NavRail.tsx").read_text()
DRY = ROOT / "fixtures/control_plane/dry_run"
REPLAY = ROOT / "fixtures/control_plane/replay"
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane"
IDS = json.loads((DRY / "IDS.json").read_text())["ids"]

PAGES_SPEC = [
    ("r22/AgentOfficePage.tsx", "control-plane/agents", "/api/v3/control-plane/agents"),
    ("r22/WorkflowTracePage.tsx", "control-plane/workflows", "/api/v3/control-plane/workflows"),
    ("r23/ResearchAttentionPage.tsx", "control-plane/research", "/api/v3/control-plane/research"),
    ("r23/DataIntegrityPage.tsx", "control-plane/data", "/api/v3/control-plane/stores"),
    ("r23/IdentityPage.tsx", "control-plane/identity", "/api/v3/control-plane/identity"),
    ("r23/NotificationsPage.tsx", "control-plane/notifications", "/api/v3/control-plane/notifications"),
    ("r24/LearningPage.tsx", "control-plane/learning", "/api/v3/control-plane/learning"),
    ("r24/MaturityPage.tsx", "control-plane/maturity", "/api/v3/control-plane/maturity"),
    ("r24/AuditPage.tsx", "control-plane/audit", "/api/v3/control-plane/audit"),
]


def test_committed_pages_and_shadow_routes_exist():
    for rel, route, endpoint in PAGES_SPEC:
        path = PAGES / rel
        assert path.is_file(), rel
        src = path.read_text()
        assert endpoint in src or endpoint.split("/")[-1] in src
        assert f'path="{route}"' in APP
    assert 'basename="/v3"' in APP
    assert 'path="agents"' in APP
    assert 'path="research-intelligence"' in APP
    assert 'path="system"' in APP
    assert 'Navigate to="/control-plane' not in APP


def test_preview_flag_and_deep_link_namespace():
    assert "CC_CONTROL_PLANE_PREVIEW" in NAV
    assert "pathname.startsWith('/control-plane')" in NAV
    assert "CONTROL_PLANE_PREVIEW" in NAV
    # Deep-link: routes are registered unconditionally; nav is gated.
    assert 'path="control-plane/agents"' in APP
    # Unknown control-plane path is not aliased onto a live page.
    assert 'path="control-plane/*"' not in APP


def test_runtime_mocks_zero_in_live_pages():
    for rel, _route, _endpoint in PAGES_SPEC:
        src = (PAGES / rel).read_text()
        assert 'data-testid="agent-detail-fixture"' not in src
        if rel.startswith("r22/AgentOfficePage"):
            assert "agentDetailUrl" in src
        if rel.startswith("r22/WorkflowTracePage"):
            assert "workflowDetailUrl" in src


def test_replay_fixtures_are_synthetic_not_source_derived():
    rows = json.loads((REPLAY / "data/runtime/workflow_traces.json").read_text())
    assert len(rows) == 120
    for row in rows:
        assert row["evidence_class"] == "HISTORICAL_REPLAY"
        assert str(row["workflow_id"]).startswith("replay.workflow.")
        assert row.get("source_sha") == "dryrun-source-sha-084674c5"
        assert not row.get("source_ref")
        assert not row.get("historical_source")


def test_real_historical_control_plane_trace_not_available_pre_deploy():
    runtime = ROOT / "data/runtime"
    assert not (runtime / "workflow_traces.json").exists()


def test_expected_local_unavailable_is_honest(monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", ROOT)
    _, agents = api.handle("/api/v3/control-plane/agents")
    assert agents["data_quality"] == "UNAVAILABLE"
    _, stores = api.handle("/api/v3/control-plane/stores")
    assert stores["data_quality"] == "UNAVAILABLE"


def test_dry_run_lineage_ids_across_surfaces(monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", DRY)
    _, wf = api.handle(f"/api/v3/control-plane/workflows/{IDS['workflow_id']}")
    types = [n["node_type"] for n in wf["data"]["nodes"]]
    for required in (
        "SOURCE_EVENT", "ENTITY", "MATERIALITY", "RESEARCH_GAP", "SPECIALIST_DISPATCH",
        "SPECIALIST_ARTIFACT", "COUNCIL", "CIO_PRODUCT", "NOTIFICATION", "CHECKPOINT",
        "OUTCOME", "LEARNING",
    ):
        assert required in types
    _, research = api.handle("/api/v3/control-plane/research")
    _, notes = api.handle("/api/v3/control-plane/notifications")
    _, learning = api.handle("/api/v3/control-plane/learning")
    _, agents = api.handle("/api/v3/control-plane/agents")
    assert any(r.get("research_id") == IDS["research_id"] or r.get("subject_id") == IDS["entity_guid"] for r in research["data"]["items"])
    assert any(n.get("notification_id") == IDS["notification_id"] for n in notes["data"]["items"])
    assert any(item.get("workflow_id") == IDS["workflow_id"] for item in learning["data"]["items"])
    assert any(a.get("agent_id") == "maria" for a in agents["data"]["items"])


def test_control_plane_read_benchmark_is_bounded(monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", REPLAY)
    measurements = {}
    for name, path in (
        ("system", "/api/v3/control-plane/system"),
        ("agents", "/api/v3/control-plane/agents"),
        ("workflows_list", "/api/v3/control-plane/workflows"),
        ("workflow_detail", "/api/v3/control-plane/workflows/replay.workflow.000"),
        ("notifications", "/api/v3/control-plane/notifications"),
        ("learning", "/api/v3/control-plane/learning"),
    ):
        t0 = time.perf_counter()
        for _ in range(20):
            status, body = api.handle(path, query={"limit": "50"})
            assert status == 200
            assert "data" in body
        measurements[name] = (time.perf_counter() - t0) / 20
    evidence = ROOT / "docs/_evidence/r20-r24/PERFORMANCE_SMOKE.json"
    payload = {
        "method": "scripts.control_plane_api.handle x20 mean seconds",
        "n_workflows": 120,
        "measurements_seconds": measurements,
        "notes": [
            "Each GET reads at most one JSON file; no JSONL scan.",
            "Pagination bounded 1..200.",
            "No invented SLO; values are local adapter measurements.",
        ],
        "regressions": [],
    }
    evidence.write_text(json.dumps(payload, indent=2) + "\n")
    assert all(v < 0.5 for v in measurements.values()), measurements


def test_replacement_matrix_has_no_regression_and_no_unknown():
    text = (ROOT / "docs/convergence/UI_REPLACEMENT_MATRIX.md").read_text()
    assert "| REGRESSION |" not in text
    allowed = {"KEEP", "REPLACE", "MERGE", "SPLIT", "RETIRE", "REDIRECT", "DEFER"}
    header = None
    disp_idx = None
    for line in text.splitlines():
        if line.startswith("| Old route") or line.startswith("| New route"):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            disp_idx = header.index("Disposition") if "Disposition" in header else None
            continue
        if not line.startswith("| `/") or disp_idx is None:
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) <= disp_idx:
            continue
        disp = cols[disp_idx].split("(")[0].strip()
        if disp in {"—", ""}:
            continue
        assert disp in allowed, (cols[0], disp)


def test_faults_do_not_render_as_healthy_empty(tmp_path, monkeypatch):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    (runtime / "identity_registry.json").write_text(json.dumps([
        {"entity_id": "x", "state": "UNRESOLVED_WITH_REASON", "unresolved_reason": "no issuer"}
    ]))
    _, identity = api.handle("/api/v3/control-plane/identity")
    assert identity["data"]["items"][0]["state"] == "UNRESOLVED_WITH_REASON"
    (runtime / "notification_receipts.json").write_text(json.dumps([
        {"notification_id": "n1", "decision": "failed", "evidence_class": "DRY_RUN"}
    ]))
    _, notes = api.handle("/api/v3/control-plane/notifications")
    assert notes["data"]["items"][0]["decision"] == "failed"
    (runtime / "workflow_traces.json").write_text(json.dumps([{
        "workflow_id": "w-fault",
        "checkpoint_id": "missing",
        "outcome_id": "missing",
        "nodes": [{"id": "e", "node_type": "source_event", "timestamp": "2026-01-01T00:00:00Z"}],
        "edges": [
            {"from": "e", "to": "checkpoint", "certainty": "UNAVAILABLE_STORE"},
            {"from": "e", "to": "outcome", "certainty": "UNAVAILABLE_STORE"},
        ],
    }]))
    _, wf = api.handle("/api/v3/control-plane/workflows/w-fault")
    certs = {e["certainty"] for e in wf["data"]["edges"]}
    assert "UNAVAILABLE_STORE" in certs
    assert wf["data_quality"] == "PARTIAL"
    (runtime / "agent_registry.json").write_text(json.dumps([
        {"agent_id": "q", "runtime_state": "BROKEN", "queue_depth": 99, "last_failure": "timeout"}
    ]))
    _, agents = api.handle("/api/v3/control-plane/agents")
    assert agents["data"]["items"][0]["queue_depth"] == 99
    assert agents["data"]["items"][0]["runtime_state"] == "BROKEN"
