"""Research governance — PR scope guard dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import pr_scope_guard as sg  # noqa: E402


def test_denylist_covers_offlimits():
    offlimits = [
        "scripts/lib/cio_acceptance_v4.py",
        "scripts/lib/cio_capital_plan.py",
        "scripts/lib/cio_strategy_knowledge.py",
        "scripts/lib/cio_seasonality_engine.py",
        "scripts/lib/advisory/kb_lessons.py",
        "scripts/agent_runtime/knowledge.py",
        "scripts/lib/hermes_research_backend.py",
        "apps/command-center-v3/src/pages/CioHub.tsx",
        "RELEASE_MANIFEST.json",
        "scripts/deploy_portfolio_server.sh",
    ]
    for f in offlimits:
        assert sg.is_denied(f), f"scope guard should deny {f}"


def test_allowlist_covers_r1_files():
    r1_files = [
        "scripts/lib/research_governance/trial_registry.py",
        "scripts/lib/research_governance/promotion_gate.py",
        "tests/test_research_governance_trial_registry.py",
        ".github/workflows/research-governance-ci.yml",
        "config/cio_research_source_catalog.json",
        "docs/investment-office/RESEARCH_GOVERNANCE.md",
        "scripts/run_research_governance_acceptance.py",
    ]
    for f in r1_files:
        assert sg.is_allowed(f), f"scope guard should allow {f}"


def test_evaluate_passes_on_allowlist_only():
    changed = [
        "scripts/lib/research_governance/enums.py",
        "tests/test_research_governance_acceptance.py",
        ".github/workflows/research-governance-ci.yml",
    ]
    result = sg.evaluate(changed)
    assert result["state"] == "PASS"
    assert result["denied"] == []
    assert result["unexpected"] == []


def test_evaluate_fails_on_offlimits():
    changed = [
        "scripts/lib/research_governance/enums.py",
        "scripts/lib/cio_acceptance_v4.py",
    ]
    result = sg.evaluate(changed)
    assert result["state"] == "FAIL"
    assert "scripts/lib/cio_acceptance_v4.py" in result["denied"]


def test_evaluate_fails_on_unexpected():
    changed = [
        "scripts/lib/research_governance/enums.py",
        "scripts/portfolio_server.py",  # not in R1 allowlist
    ]
    result = sg.evaluate(changed)
    assert result["state"] == "FAIL"
    assert "scripts/portfolio_server.py" in result["unexpected"]


def test_evaluate_empty_is_pass():
    assert sg.evaluate([])["state"] == "PASS"
