"""AGENTS.md 24.0.0 ACTIVE — Mergify + host deploy pins (laconic)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
AIWP = (ROOT / "AI_WORK_POLICY.md").read_text(encoding="utf-8")
FOUNDATION = ROOT / "docs" / "ops" / "MERGIFY_DEPLOY_FOUNDATION.md"
EMERGENCY = ROOT / "docs" / "ops" / "EMERGENCY_MANUAL_PROMOTE.md"


def test_header_is_24_0_0_active():
    m = re.search(r"```\n(Policy-Version:.*?)```", AGENTS, re.DOTALL)
    assert m
    block = m.group(1)
    assert "Policy-Version:      24.0.0" in block
    assert "Status:              ACTIVE" in block
    assert "Effective-Date:      2026-10-26" in block
    assert "Supersedes:          22.0.0" in block


def test_banner_and_section_25_10_present():
    assert "24.0.0 is ACTIVE (MAJOR) — Mergify merges" in AGENTS
    assert "## 25.10 Mergify + host deploy (24.0.0, ACTIVE)" in AGENTS
    assert "DeployOnMainReceipt@v1" in AGENTS
    assert "TRADEAI_EMERGENCY_RELEASE_SHA" in AGENTS
    assert "APPROVE_AGENTS_POLICY_24_0_0" in AGENTS


def test_section_17_mergify_items():
    assert "Mergify deploy (24.0.0, §25.10)" in AGENTS
    assert "emergency_manual_promote.sh" in AGENTS


def test_version_history_row():
    assert re.search(r"\|\s*24\.0\.0\s*\|.*ACTIVE.*MAJOR.*Mergify", AGENTS)


def test_foundation_docs_exist():
    assert FOUNDATION.is_file()
    assert EMERGENCY.is_file()
    assert "Mergify merges green PRs" in FOUNDATION.read_text(encoding="utf-8")
    assert "TRADEAI_EMERGENCY_RELEASE_SHA" in EMERGENCY.read_text(encoding="utf-8")


def test_ai_work_policy_section_28_mentions_mergify():
    assert "24.0.0" in AIWP
    assert "Mergify" in AIWP
    assert "deploy_on_main" in AIWP
    assert "24.0.0 ACTIVE" in AIWP or "AGENTS.md 24.0.0 ACTIVE" in AIWP
