from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "apps/command-center-v3/src/pages/ReEntryPageV4.tsx"
ANALYST = ROOT / "apps/command-center-v3/src/components/reentry/ReEntryAnalystLookthroughBoard.tsx"
RESISTANCE = ROOT / "apps/command-center-v3/src/components/reentry/ReEntryResistanceBoard.tsx"
RUNNER = ROOT / "scripts/watch_alerts_eval.py"


def read(path: Path) -> str:
    assert path.exists(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_reentry_page_mounts_both_intelligence_boards():
    page = read(PAGE)
    assert "ReEntryResistanceBoard" in page
    assert "ReEntryAnalystLookthroughBoard" in page
    assert "<ReEntryResistanceBoard />" in page
    assert "<ReEntryAnalystLookthroughBoard />" in page


def test_professional_analyst_board_uses_proven_map_endpoint():
    source = read(ANALYST)
    assert "/api/v2/pro-analyst/pills?map=1" in source
    assert "/api/v2/portfolio/lookthrough" in source
    assert "PROFESSIONAL" in source.upper()
    assert "ETF/FUND LOOK-THROUGH" in source
    assert "UNDERWEIGHT" in source
    assert "OVERWEIGHT" in source
    assert "AT TARGET" in source
    assert "REDUCED SOURCE" in source
    assert "INCREASED DESTINATION" in source
    assert "Fund-specific holdings unavailable; portfolio-wide look-through is not relabeled as fund-specific." in source


def test_resistance_board_exposes_required_closed_session_pills():
    source = read(RESISTANCE)
    assert "RESISTANCE / RECLAIM BOARD" in source
    assert "Closed sessions only" in source
    assert "intraday crosses never count as a hold" in source
    for state in ("ABOVE", "BELOW", "TESTING", "UNAVAILABLE"):
        assert state in source
    assert "hold began" in source
    assert "tests" in source
    assert "portfolio.reentry.resistance.v1" in source


def test_existing_scheduled_runner_refreshes_resistance_cache():
    runner = read(RUNNER)
    assert "refresh_resistance_cache" in runner
    assert "resistance rows refreshed" in runner
