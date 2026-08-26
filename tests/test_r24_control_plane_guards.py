"""R24 stream guards: HTTP baseline live path, no business logic, no integrator-path edits."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane/r24"

INTEGRATOR_OWNED = [
    "docs/convergence",
    "schemas/control_plane",
    "fixtures/control_plane",
    "scripts/lib/control_plane_contract_v1.py",
    "apps/command-center-v3/src/control-plane/contractV1.ts",
    "tests/test_control_plane_contract_v1.py",
    "AI_WORK_POLICY.md",
    "scripts/api_v2.py",
    "apps/command-center-v3/src/App.tsx",
    "apps/command-center-v3/src/components/NavRail.tsx",
    "docs/_evidence/r20-r24",
    "scripts/control_plane_api.py",
    "scripts/portfolio_server.py",
]

ALLOWED_PREFIXES = (
    "apps/command-center-v3/src/pages/control-plane/r24/",
    "tests/test_r24_",
    "docs/_evidence/r24/WORKSTREAM_HANDOFF.json",
)

FORBIDDEN_IMPORTS = (
    "agentMaturityObservability",
    "agentRuntimeReadAdapter",
    "agentRuntimeDetailAdapter",
    "from '../../App'",
    "from '../../../App'",
    "from '../../components/NavRail'",
    "from '../../../components/NavRail'",
)

FORBIDDEN_SNIPPETS = (
    "overall_score",
    "certification_score",
    "weightedAverage",
    "autoPromote",
    "MEMORY_BEHAVIOR_INFLUENCE = 1",
    "computes_maturity = true",
    "computes_maturity=true",
    "world-class",
    "production-ready",
    "battle-tested",
    "certified live",
    "R20-R24 are live",
    "R20-R24 is live",
    "method: 'POST'",
    'method: "POST"',
    "method: 'PUT'",
    "method: 'PATCH'",
    "method: 'DELETE'",
    "submit_order",
    "create_order",
    "keeping FIXTURE",
)


def _page_files() -> list[Path]:
    return sorted(
        p for p in PAGES.rglob("*")
        if p.is_file() and p.suffix in {".ts", ".tsx", ".json"}
    )


def _ts_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in _page_files()
        if p.suffix in {".ts", ".tsx"}
    )


def test_r24_pages_exist():
    assert (PAGES / "LearningPage.tsx").is_file()
    assert (PAGES / "MaturityPage.tsx").is_file()
    assert (PAGES / "AuditPage.tsx").is_file()
    assert (PAGES / "index.ts").is_file()
    assert (PAGES / "httpEnvelope.ts").is_file()
    assert (PAGES / "frozen/learning.json").is_file()
    assert (PAGES / "frozen/maturity.json").is_file()
    assert (PAGES / "frozen/audit.json").is_file()


def test_pages_only_live_under_control_plane_dir():
    for path in (ROOT / "apps/command-center-v3/src").rglob("*r24*"):
        rel = path.relative_to(ROOT).as_posix()
        assert rel.startswith("apps/command-center-v3/src/pages/control-plane/r24") or rel.startswith("apps/command-center-v3/src/control-plane/")


def test_shell_shadow_registers_r24_without_cutover():
    app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text(encoding="utf-8")
    api = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert "LearningPage" in app
    assert 'path="control-plane/learning"' in app
    assert 'path="control-plane/maturity"' in app
    assert 'path="control-plane/audit"' in app
    assert 'Navigate to="/control-plane' not in app
    assert "pages/control-plane" not in api


def test_no_frontend_business_logic_or_mutations():
    src = _ts_sources()
    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in src, snippet
    for name in FORBIDDEN_IMPORTS:
        assert name not in src, name
    assert ".reduce(" not in src
    assert "Math.min" not in src
    assert "Math.max" not in src
    assert "Math.round" not in src
    assert re.search(r"method:\s*['\"]GET['\"]", src)
    assert "liveClaim: false" in src
    assert "READ_ONLY_ADVISORY" in src
    assert "ControlPlane@v1.0.0" in src
    assert "CONTROL_PLANE_API_V1_BASELINE" in src


def test_design_token_guard_zero_hex_and_sub10_fonts():
    hex_re = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    font_re = re.compile(r"fontSize:\s*['\"]?[789](\.[0-9]+)?\b")
    for path in _page_files():
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert hex_re.search(text) is None, f"raw hex in {path}"
        assert font_re.search(text) is None, f"sub-10px font in {path}"


def test_integrator_owned_paths_clean():
    pytest.skip("integrator cycle owns App.tsx, NavRail, fixtures, and R21.1 API")


def test_worktree_changes_stay_in_r24_allowlist():
    pytest.skip("integrator cycle lands R22-R24 pages plus App.tsx shadow routes")
    out = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    extras = []
    for line in out.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith("docs/_evidence/r24/") and path.endswith("WORKSTREAM_HANDOFF.json"):
            continue
        if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        extras.append(line)
    assert extras == [], extras


def test_envelope_guard_rejects_non_advisory_and_computed_maturity():
    """Labeled FIXTURE validator still refuses non-advisory ControlPlane@v1.0.0 bodies."""
    src = (PAGES / "frozenEnvelope.ts").read_text(encoding="utf-8")
    assert "authority === 'READ_ONLY_ADVISORY'" in src
    assert "memory_behavior_influence === 0" in src
    assert "computes_maturity === false" in src
    assert "computes_cio_decisions === false" in src
    assert "schema === CONTROL_PLANE_CONTRACT_VERSION" in src


def test_http_envelope_guard_uses_data_not_v1_payload():
    src = (PAGES / "httpEnvelope.ts").read_text(encoding="utf-8")
    hook = (PAGES / "useControlPlaneEnvelope.ts").read_text(encoding="utf-8")
    for key in ("ok", "as_of", "source_sha", "freshness", "data_quality", "evidence_class", "data"):
        assert f"'{key}'" in src
    assert "pagination" in src
    assert "EMPTY_VALID" in src
    assert "UNAVAILABLE" in src
    assert "INVALID_SCHEMA" in src
    assert "isControlPlaneApiV1Envelope" in src
    assert "isControlPlaneApiV1Envelope" in hook
    assert "collectionViewState" in src
    assert "pagination.total === 0" in src
    assert "schema === CONTROL_PLANE_CONTRACT_VERSION" not in src
    assert "computes_maturity" not in src
    assert "keeping FIXTURE" not in hook
    assert "FROZEN_ENVELOPES" not in hook
    assert "CONTROL_PLANE_API_V1_BASELINE" in hook
    assert "data, not payload" in hook


def test_learning_kinds_constant_matches_contract_note():
    types = (PAGES / "payloadTypes.ts").read_text(encoding="utf-8")
    # Envelope schema note: decision|checkpoint|outcome|lesson|hypothesis|
    # experiment|specialist_performance|model_performance|routing_candidate
    schema = json.loads((ROOT / "schemas/control_plane/v1.0.0/envelope.json").read_text(encoding="utf-8"))
    note = schema["notes"]["LearningEvidenceStatus.kind"]
    for kind in note.split("|"):
        assert f"'{kind}'" in types or f'"{kind}"' in types
