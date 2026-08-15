"""Research governance — PR scope guard tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import pr_scope_guard  # noqa: E402


def test_denies_off_limits_files():
    for f in (
        "scripts/lib/cio_acceptance_v4.py",
        "scripts/lib/cio_capital_plan.py",
        "scripts/lib/cio_strategy_knowledge.py",
        "scripts/lib/cio_seasonality_engine.py",
        "scripts/lib/advisory/kb_lessons.py",
        "scripts/agent_runtime/knowledge.py",
        "scripts/lib/hermes_research_backend.py",
        "apps/command-center-v3/src/App.tsx",
        "RELEASE_MANIFEST.json",
        "scripts/deploy_portfolio_server.sh",
        "deploy/foo.sh",
    ):
        assert pr_scope_guard.is_denied(f), f


def test_allows_research_files():
    for f in (
        "scripts/lib/research_governance/trial_registry.py",
        "tests/test_research_governance_trial_registry.py",
        ".github/workflows/research-governance-ci.yml",
        "config/cio_research_source_catalog.json",
        "docs/investment-office/RESEARCH_GOVERNANCE.md",
        "scripts/lib/research_governance/mechanics/fixed_income.py",
        "tests/test_research_mechanics_etf.py",
        "docs/investment-office/R2_DETERMINISTIC_MECHANICS.md",
    ):
        assert pr_scope_guard.is_allowed(f), f


def test_evaluate_pass_on_allowlisted_only():
    r = pr_scope_guard.evaluate([
        "scripts/lib/research_governance/pbo.py",
        "tests/test_research_governance_pbo.py",
    ])
    assert r["state"] == "PASS"
    assert r["changed_count"] == 2


def test_evaluate_fail_on_denied():
    r = pr_scope_guard.evaluate(["scripts/lib/cio_capital_plan.py"])
    assert r["state"] == "FAIL"
    assert r["denied"] == ["scripts/lib/cio_capital_plan.py"]


def test_evaluate_fail_on_unexpected():
    r = pr_scope_guard.evaluate(["some/random/file.py"])
    assert r["state"] == "FAIL"
    assert r["unexpected"] == ["some/random/file.py"]


def test_evaluate_normalizes_generator_once():
    # A generator must be consumed exactly once and still report the right count.
    gen = (f for f in ["scripts/lib/research_governance/cv.py", "tests/test_research_governance_cv.py"])
    r = pr_scope_guard.evaluate(gen)
    assert r["state"] == "PASS"
    assert r["changed_count"] == 2
