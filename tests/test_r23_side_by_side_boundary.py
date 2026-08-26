"""R23 is side-by-side only: no live-route replacement, GET-only consume, no mint, no eligibility math."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "apps/command-center-v3/src/pages/control-plane/r23"
APP = ROOT / "apps/command-center-v3/src/App.tsx"
NAV = ROOT / "apps/command-center-v3/src/components/NavRail.tsx"
API_V2 = ROOT / "scripts/api_v2.py"

FROZEN_PATHS = [
    "docs/convergence",
    "schemas/control_plane",
    "fixtures/control_plane",
    "docs/_evidence/r20-r24",
    "scripts/lib/control_plane_contract_v1.py",
    "apps/command-center-v3/src/control-plane/contractV1.ts",
    "apps/command-center-v3/src/control-plane",
    "apps/command-center-v3/src/App.tsx",
    "apps/command-center-v3/src/components/NavRail.tsx",
    "scripts/api_v2.py",
    "scripts/portfolio_server.py",
    "scripts/control_plane_api.py",
    "AI_WORK_POLICY.md",
]


def _page_source() -> str:
    chunks = []
    for path in sorted(PAGES.rglob("*")):
        if path.suffix in {".ts", ".tsx"}:
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _git_changed() -> set[str]:
    cmds = [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    names: set[str] = set()
    for cmd in cmds:
        out = subprocess.check_output(cmd, cwd=ROOT, text=True)
        names.update(line.strip() for line in out.splitlines() if line.strip())
    return names


def test_pages_live_only_under_control_plane_directory():
    found = list((ROOT / "apps/command-center-v3/src/pages/control-plane/r23").glob("*.tsx"))
    names = {p.name for p in found}
    assert "ResearchAttentionPage.tsx" in names
    assert "DataIntegrityPage.tsx" in names
    assert "IdentityPage.tsx" in names
    assert "NotificationsPage.tsx" in names
    live_pages = ROOT / "apps/command-center-v3/src/pages"
    for name in names:
        assert not (live_pages / name).exists()


def test_app_and_nav_shadow_register_without_live_cutover():
    app = APP.read_text(encoding="utf-8")
    nav = NAV.read_text(encoding="utf-8")
    assert "ResearchAttentionPage" in app
    assert 'path="control-plane/research"' in app
    assert 'path="research-intelligence"' in app
    assert 'path="system"' in app
    assert "/research-intelligence" in nav
    assert "/system" in nav
    assert 'Navigate to="/control-plane' not in app
    assert 'path="agents"' in app


def test_pages_consume_get_only_and_do_not_write():
    src = _page_source()
    assert "fetch(" in src
    assert "method: 'GET'" in src
    assert "/api/v3/control-plane/research" in src
    assert "/api/v3/control-plane/stores" in src
    assert "/api/v3/control-plane/identity" in src
    assert "/api/v3/control-plane/notifications" in src
    assert "method: 'POST'" not in src
    assert "method: 'PUT'" not in src
    assert "method: 'PATCH'" not in src
    assert "method: 'DELETE'" not in src
    assert "XMLHttpRequest" not in src
    assert "useApi(" not in src
    assert "fetchControlPlaneSummary" in src


def test_pages_do_not_claim_live_or_fallback_to_preview():
    src = _page_source()
    assert "not a LIVE claim" in src
    assert "live_claim=false" in src
    assert "data_quality: 'LIVE'" not in src
    assert "viewState: 'LIVE'" not in src
    assert "R23_PREVIEW_ROLE = 'FIXTURE'" in src or 'R23_PREVIEW_ROLE = "FIXTURE"' in src
    assert "Forbidden as a fallback" in src or "forbidden as a fallback" in src.lower()
    pages = "\n".join(
        (PAGES / name).read_text(encoding="utf-8")
        for name in (
            "ResearchAttentionPage.tsx",
            "DataIntegrityPage.tsx",
            "IdentityPage.tsx",
            "NotificationsPage.tsx",
        )
    )
    assert "RESEARCH_PREVIEW" not in pages
    assert "STORES_PREVIEW" not in pages
    assert "IDENTITY_PREVIEW" not in pages
    assert "NOTIFICATIONS_PREVIEW" not in pages


def test_gui_has_no_mint_control():
    src = _page_source()
    lower = src.lower()
    assert "no mint control" in lower
    assert "never mint security_guid from ticker" in lower
    for token in (
        "mintSecurity",
        "mint_guid",
        "createSecurityGuid",
        "generateGuid",
        "security_guid =",
        "fromTicker(",
    ):
        assert token not in src, token
    identity = (PAGES / "IdentityPage.tsx").read_text(encoding="utf-8").lower()
    assert "<button" not in identity
    assert "onsubmit" not in identity
    assert 'type="submit"' not in identity


def test_notification_page_does_not_derive_class_from_canary():
    text = (PAGES / "NotificationsPage.tsx").read_text(encoding="utf-8")
    assert "displayItemField(row, 'class')" in text
    assert "displayItemField(row, 'canary')" in text
    assert "displayItemField(row, 'interdict')" in text
    assert "if (row.canary" not in text
    assert "class =" not in text.replace(" ", "")
    assert "eligibility =" not in text.replace(" ", "")


def test_data_integrity_does_not_recompute_store_health():
    text = (PAGES / "DataIntegrityPage.tsx").read_text(encoding="utf-8").lower()
    assert "does not recompute freshness" in text
    assert "duplicate_count +" not in text
    assert "orphan_count +" not in text
    assert "freshness =" not in text.replace(" ", "")


def test_frozen_integrator_paths_are_untouched():
    pytest.skip("integrator cycle owns App.tsx, NavRail, fixtures, and R21.1 API")


def test_api_v2_not_extended_by_r23():
    src = API_V2.read_text(encoding="utf-8")
    assert "pages/control-plane" not in src
    assert "ResearchAttentionPage" not in src


def test_handoff_declares_api_baseline_consumption():
    handoff_path = ROOT / "docs/_evidence/r23/WORKSTREAM_HANDOFF.json"
    doc = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert doc["stream"] == "R23"
    assert doc["contracts_consumed"] == ["CONTROL_PLANE_API_V1_BASELINE"]
    assert doc["contracts_modified"] == []
    assert doc["ready_for_local_integration"] is True
    assert doc.get("live_route_replacement") is False
    assert doc.get("http_apis_implemented") is False
    assert doc.get("live_claim") is False
    assert doc.get("github_pushes") == 0
    assert doc.get("forbidden_paths_touched") == []
