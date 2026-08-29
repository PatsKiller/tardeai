"""Wave 2 slice 09: CioHub coverage card reads home.coverage (no Telegram)."""
from __future__ import annotations

from pathlib import Path

HUB = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "command-center-v3"
    / "src"
    / "pages"
    / "CioHub.tsx"
)


def test_ciohub_has_coverage_card_after_trust_strip():
    src = HUB.read_text(encoding="utf-8")
    assert 'data-testid="cio-coverage-card"' in src
    assert "CoverageCard" in src
    assert "home.coverage" in src
    # Card sits in CioNowSection after TrustStrip
    trust_i = src.index("<TrustStrip")
    cov_i = src.index("<CoverageCard")
    assert cov_i > trust_i
    assert "OfficeCoverage" in src
    assert "No Telegram" in src


def test_home_type_includes_coverage():
    src = HUB.read_text(encoding="utf-8")
    assert "coverage?: OfficeCoverage" in src
    assert "thesis_count" in src
    assert "held_n" in src
