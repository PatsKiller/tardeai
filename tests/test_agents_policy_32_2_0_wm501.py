"""AGENTS.md 32.2.0: §9.6 Wealth Management 501 references real, present guide files (no placeholder paths)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
GUIDE = "docs/design/WEALTH_MANAGEMENT_501.md"
ADDENDUM = "docs/design/WEALTH_MANAGEMENT_501_ADDENDUM_V1_1.md"


def _section() -> str:
    m = re.search(r"^## 9\.6 Wealth Management 501.*?(?=^# 10 · )", AGENTS, re.S | re.M)
    assert m, "§9.6 Wealth Management 501 section missing"
    return m.group(0)


def test_section_links_resolve_to_existing_files():
    sec = _section()
    for rel in (GUIDE, ADDENDUM):
        assert rel in sec
        assert (ROOT / rel).is_file(), rel


def test_no_placeholder_paths_in_section():
    sec = _section()
    assert "AGENTS_WM501_SECTION.md" not in sec
    assert "placeholder" not in sec.lower()


def test_guide_versions_and_scope_markers():
    v10 = (ROOT / GUIDE).read_text(encoding="utf-8")
    v11 = (ROOT / ADDENDUM).read_text(encoding="utf-8")
    assert "Version 1.0" in v10
    assert "addendum v1.1" in v11
    assert "## Route migration and retirement" in v11
    assert "not a claim that the features are deployed" in v11


def test_section_keeps_safety_boundaries():
    sec = _section()
    assert "does not erase them" in sec
    assert "2FA" in sec and "broker locks" in sec
    assert "Never expose credentials" in sec
