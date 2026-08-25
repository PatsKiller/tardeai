from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cio_brain_is_default_integrated_operator_surface() -> None:
    hub = (ROOT / "apps/command-center-v3/src/pages/CioHub.tsx").read_text(encoding="utf-8")
    brain = (ROOT / "apps/command-center-v3/src/components/cio/CioBrainPanel.tsx").read_text(encoding="utf-8")
    assert "'cio-brain': 'CIO BRAIN'" in hub
    assert "const initialTab: Tab = TABS.includes(tabParam) ? tabParam : 'cio-brain'" in hub
    for testid in (
        "cio-brain-portfolio-thesis",
        "cio-brain-capital-deployment",
        "cio-brain-market-context",
        "cio-brain-seasonality",
        "cio-brain-methodology",
        "cio-brain-learning",
        "cio-brain-memory",
        "cio-brain-operator-policy",
        "cio-brain-system-health",
        "cio-brain-what-changed",
        "cio-brain-what-it-knows",
        "cio-brain-what-it-does-not-know",
        "cio-brain-material-situations",
        "cio-brain-current-recommendation",
        "cio-brain-notifications",
        "cio-brain-memory-shadow",
        "cio-brain-attention",
        "cio-brain-uncertainty",
        "cio-brain-missing-policy",
        "cio-brain-suppressed",
        "cio-brain-next",
        "cio-brain-intelligence-lifecycle",
        "cio-brain-graph-context",
        "cio-brain-curation-history",
        "cio-brain-model-performance",
        "cio-brain-unwired",
        "cio-brain-knowledge-gaps",
    ):
        assert testid in brain
    assert "Executable order: NONE" in brain
    assert "behavior influence 0" in brain
