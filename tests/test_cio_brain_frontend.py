from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cio_overview_is_default_scorecard_landing() -> None:
    hub = (ROOT / "apps/command-center-v3/src/pages/CioHub.tsx").read_text(encoding="utf-8")
    tabs = (ROOT / "apps/command-center-v3/src/lib/cioHubTabs.ts").read_text(encoding="utf-8")
    strip = (ROOT / "apps/command-center-v3/src/components/cio/CioScorecardStrip.tsx").read_text(encoding="utf-8")
    judgment = (ROOT / "apps/command-center-v3/src/components/cio/CioJudgmentBand.tsx").read_text(encoding="utf-8")
    modal = (ROOT / "apps/command-center-v3/src/components/cio/CioEvidenceModal.tsx").read_text(encoding="utf-8")

    assert "CIO_HUB_DEFAULT_TAB" in tabs
    assert "overview" in tabs
    assert "'cio-brain': 'overview'" in tabs
    assert "'cio-now': 'decisions'" in tabs
    assert "resolveCioHubTab" in hub
    assert "CioScorecardStrip" in hub
    assert "CioJudgmentBand" in hub
    assert "CioEvidenceModal" in hub
    assert 'data-testid="cio-overview"' in hub
    assert 'data-testid="cio-scorecard-strip"' in strip
    assert 'data-testid="cio-judgment-band"' in judgment
    assert 'data-testid="cio-evidence-modal"' in modal
    assert "/api/v3/cio/scorecard" in hub


def test_cio_brain_panel_bands_still_present_for_evidence_deep_view() -> None:
    brain = (ROOT / "apps/command-center-v3/src/components/cio/CioBrainPanel.tsx").read_text(encoding="utf-8")
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
        "cio-brain-learning-cockpit",
    ):
        assert testid in brain
    assert "LIVE" in brain and "GOLDEN_SHADOW" in brain
    assert "HISTORICAL_VALIDATED" in brain
    assert "Executable order: NONE" in brain
    assert "behavior influence 0" in brain


def test_scorecard_api_route_wired() -> None:
    api = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    cio = (ROOT / "scripts/api_v3_cio.py").read_text(encoding="utf-8")
    assert 'if p == "scorecard":' in api
    assert "get_cio_scorecard" in cio
    assert "scripts.lib.cio_scorecard" in cio
