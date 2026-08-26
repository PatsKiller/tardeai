"""R22 pages consume CONTROL_PLANE_API_V1_BASELINE summary GET APIs.

They must not compute business states or treat fixtures as live list data.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts.lib.control_plane_contract_v1 import RUNTIME_STATUS, WORKFLOW_NODE_KINDS

ROOT = Path(__file__).resolve().parents[1]
CP = ROOT / "apps/command-center-v3/src/pages/control-plane/r22"
OFFICE = CP / "AgentOfficePage.tsx"
TRACE = CP / "WorkflowTracePage.tsx"
VIEW = CP / "contractView.ts"
FETCH = CP / "fetchControlPlane.ts"
CHROME = CP / "controlPlaneChrome.tsx"

LINEAGE_ARROW = (
    "event → entity → materiality → graph → research → specialist → "
    "council → cio → notification → checkpoint → outcome → learning"
)

FORBIDDEN_PATH_PREFIXES = (
    "schemas/control_plane/",
)
FORBIDDEN_PATHS = {
    "scripts/lib/control_plane_contract_v1.py",
    "apps/command-center-v3/src/control-plane/contractV1.ts",
    "scripts/api_v2.py",
    "AI_WORK_POLICY.md",
    "tests/test_control_plane_contract_v1.py",
}

COMPUTE_PATTERNS = (
    r"function\s+computeMaturity\b",
    r"function\s+computeCio\b",
    r"function\s+computeNotification\b",
    r"function\s+classifyNotification\b",
    r"inferRuntimeStatus",
    r"infer_runtime",
    r"computes_maturity\s*[:=]\s*true",
    r"computes_cio_decisions\s*[:=]\s*true",
    r"computes_notification_eligibility\s*[:=]\s*true",
    r"computes_agent_state\s*[:=]\s*true",
    r"maturityScore\s*[:=]",
    r"notification_class\s*[:=]",
    r"cio_decision\s*[:=]",
)

AGENT_LIST_KEYS = (
    "agent",
    "agent_id",
    "role",
    "runtime_state",
    "state",
    "last_wake",
    "wake_reason",
    "current_task",
    "entity",
    "entity_refs",
    "queue_depth",
    "queue",
    "last_success",
    "last_failure",
    "last_artifact",
    "last_artifact_id",
    "research_route",
    "model_route",
    "route",
    "model",
    "latency",
    "cost",
    "next_eligible_wake",
    "evidence_class",
)


def _src_files() -> list[Path]:
    return sorted(p for p in CP.rglob("*") if p.suffix in {".ts", ".tsx"} and p.is_file())


def _all_src() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _src_files())


def _changed_paths() -> set[str]:
    cmds = (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    out: set[str] = set()
    for cmd in cmds:
        text = subprocess.check_output(cmd, cwd=ROOT, text=True)
        out.update(p for p in text.splitlines() if p.strip())
    return out


def _quoted_const_list(src: str, const_name: str) -> list[str]:
    match = re.search(rf"export const {const_name} = \[([^\]]+)\]", src, re.S)
    assert match, const_name
    return re.findall(r"'([^']+)'", match.group(1))


def test_agent_office_source_lists_every_runtime_status():
    src = OFFICE.read_text(encoding="utf-8") + "\n" + VIEW.read_text(encoding="utf-8")
    for state in RUNTIME_STATUS:
        assert state in src
    listed = _quoted_const_list(VIEW.read_text(encoding="utf-8"), "RUNTIME_STATUS_ORDER")
    assert listed == list(RUNTIME_STATUS)


def test_workflow_trace_source_lists_lineage_in_order():
    src = TRACE.read_text(encoding="utf-8")
    assert LINEAGE_ARROW in src
    kinds = _quoted_const_list(VIEW.read_text(encoding="utf-8"), "WORKFLOW_LINEAGE_ORDER")
    assert kinds == list(WORKFLOW_NODE_KINDS)
    assert "WORKFLOW_LINEAGE_ARROW" in src
    assert "WORKFLOW_LINEAGE_ORDER" in src


def test_tsx_does_not_compute_maturity_notification_or_cio():
    src = _all_src()
    for pattern in COMPUTE_PATTERNS:
        assert re.search(pattern, src) is None, pattern
    assert "agentMaturityObservability" not in src
    assert "agentRuntimeMonitoring" not in src
    assert "useApi(" not in src
    assert "/api/v2/agents" not in src
    assert "/api/v2/system" not in src
    assert "process.pid" not in src
    assert "ps aux" not in src
    office = OFFICE.read_text(encoding="utf-8")
    assert "does not infer" in office.lower() or "does not infer RuntimeStatus" in office
    assert "runtime_state" in office
    assert "absent" in office
    trace = TRACE.read_text(encoding="utf-8")
    assert "opaque" in trace.lower() or "not computed" in trace.lower()


def test_pages_fetch_summary_urls():
    src = _all_src()
    helper = FETCH.read_text(encoding="utf-8")
    office = OFFICE.read_text(encoding="utf-8")
    trace = TRACE.read_text(encoding="utf-8")
    assert "/api/v3/control-plane/agents" in helper
    assert "/api/v3/control-plane/workflows" in helper
    assert "/api/v3/control-plane/agents" in office
    assert "/api/v3/control-plane/workflows" in trace
    assert "fetch(" in helper
    assert "LOADING" in office
    assert "LOADING" in trace
    assert "CONTROL_PLANE_API_V1_BASELINE" in src
    assert "XMLHttpRequest" not in src
    assert "useControlPlaneSummary(CONTROL_PLANE_AGENTS_URL)" in office
    assert "useControlPlaneSummary(CONTROL_PLANE_WORKFLOWS_URL)" in trace


def test_pages_call_r21_1_detail_as_live_get():
    helper = FETCH.read_text(encoding="utf-8")
    office = OFFICE.read_text(encoding="utf-8")
    trace = TRACE.read_text(encoding="utf-8")
    assert "agentDetailUrl" in helper
    assert "workflowDetailUrl" in helper
    assert "agentDetailUrl" in office
    assert "workflowDetailUrl" in trace
    assert "/api/v3/control-plane/agents/" in helper
    assert "/api/v3/control-plane/workflows/" in helper
    assert helper.count("fetch(") == 1
    assert "POST" not in helper or 'method: \'GET\'' in helper or 'method: "GET"' in helper


def test_unavailable_empty_valid_invalid_schema_are_explicit():
    src = _all_src()
    chrome = CHROME.read_text(encoding="utf-8")
    helper = FETCH.read_text(encoding="utf-8")
    for quality in ("AVAILABLE", "UNAVAILABLE", "INVALID_SCHEMA", "STALE", "DEGRADED", "EMPTY_VALID"):
        assert quality in src, quality
        assert quality in helper or quality in chrome
    assert "EMPTY_VALID = data_quality AVAILABLE AND pagination.total === 0" in helper
    assert "ok=true with UNAVAILABLE is real" in helper or "ok=true with UNAVAILABLE is real" in chrome
    assert "not a LIVE claim" in src
    listed = _quoted_const_list(helper, "DATA_QUALITY_VALUES")
    assert listed == [
        "AVAILABLE",
        "UNAVAILABLE",
        "INVALID_SCHEMA",
        "STALE",
        "DEGRADED",
        "EMPTY_VALID",
    ]


def test_remaining_mocks_are_labeled_test_fixture():
    office = OFFICE.read_text(encoding="utf-8")
    trace = TRACE.read_text(encoding="utf-8")
    assert 'data-role="TEST_FIXTURE"' in office
    assert 'data-role="TEST_FIXTURE"' in trace
    assert 'data-testid="agent-detail-fixture"' not in office
    assert 'data-testid="agent-detail"' in office
    assert 'data-testid="workflow-lineage"' in trace
    assert "not a runtime substitute" in office
    assert "not a runtime substitute" in trace


def test_agent_list_keys_are_explicit_or_absent():
    office = OFFICE.read_text(encoding="utf-8")
    for key in AGENT_LIST_KEYS:
        assert key in office, key
    assert "absent" in office
    assert "do not invent" in office.lower() or "not invented" in office.lower() or "Do not invent" in office


def test_pages_do_not_replace_live_routes():
    app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text(encoding="utf-8")
    nav = (ROOT / "apps/command-center-v3/src/components/NavRail.tsx").read_text(encoding="utf-8")
    assert "AgentOfficePage" in app
    assert "WorkflowTracePage" in app
    assert 'path="control-plane/agents"' in app
    assert 'path="agents"' in app
    assert 'Navigate to="/control-plane' not in app
    assert "/agents" in nav


def test_new_pages_have_zero_raw_hex_and_sub10_fonts():
    hex_re = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    font_re = re.compile(r"fontSize:\s*['\"]?[789](\.[0-9]+)?\b")
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        assert not hex_re.search(text), path
        assert not font_re.search(text), path


def test_forbidden_integrator_paths_untouched_in_worktree():
    for path in _changed_paths():
        assert path not in FORBIDDEN_PATHS, path
        for prefix in FORBIDDEN_PATH_PREFIXES:
            assert not path.startswith(prefix), path
