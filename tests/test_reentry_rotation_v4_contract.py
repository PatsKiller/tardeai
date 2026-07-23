from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "apps/command-center-v3/src/components/reentry/ReEntryRotationWorkspace.tsx"
REENTRY = ROOT / "apps/command-center-v3/src/pages/ReEntryPageV4.tsx"
REDEPLOY = ROOT / "apps/command-center-v3/src/pages/RedeployDeskIntegrated.tsx"
APP = ROOT / "apps/command-center-v3/src/App.tsx"
REQ = ROOT / "docs/features/PORTFOLIO_REENTRY_ROTATION_INTELLIGENCE_REQUIREMENTS_v4.md"


def text(path: Path) -> str:
    assert path.exists(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_authoritative_routes_are_mounted():
    app = text(APP)
    assert "ReEntryPage" in app
    assert 'path="portfolio/re-entry"' in app
    assert "RedeployDeskIntegrated" in app
    assert 'path="redeploy"' in app
    assert "ReEntryRotationWorkspace" in text(REENTRY)
    assert "ReEntryRotationWorkspace" in text(REDEPLOY)


def test_operator_choices_and_baseline_truth_are_recorded():
    req = text(REQ)
    for choice in ("1A", "2A", "3A", "4A", "5A"):
        assert choice in req
    assert "Single-symbol exit and re-entry monitoring: **substantially present**" in req
    assert "Complete trend-direction intelligence: **incomplete**" in req
    assert "Capital lineage and SCHG/SCHD rotation-back intelligence: **not yet implemented**" in req


def test_mandate_and_strategy_flags_are_independent():
    source = text(WORKSPACE)
    for mandate in ("core", "satellite", "hedge", "unclassified"):
        assert mandate in source
    for flag in ("growth", "compounding", "dividend", "swing", "short", "defensive", "hedge", "rotation"):
        assert f"'{flag}'" in source
    assert "SYMBOL MANDATE" in source
    assert "INDEPENDENT STRATEGY FLAGS" in source
    assert "SELECTED EXIT EVENT" in source


def test_rotation_link_contains_required_lineage_fields():
    source = text(WORKSPACE)
    required = (
        "sourceSymbol", "destinationSymbol", "account", "amountMoved", "sourceShares",
        "sourceExitDate", "sourceExitPrice", "destinationPurchaseDate", "destinationCost",
        "destinationShares", "intendedDurationDays", "switchType", "targetSourceAllocationPct",
        "returnMode", "tranches", "confirmed", "rsThresholdPct", "taxClear",
        "accountClear", "settlementClear",
    )
    for item in required:
        assert item in source
    assert "[25, 25, 50]" in source
    assert "Operator confirms capital lineage" in source


def test_both_side_intelligence_and_composite_gate_are_present():
    source = text(WORKSPACE)
    for phrase in (
        "ROTATION PAIRS — BOTH-SIDE MONITORING",
        "RETURN-TO-GROWTH COMPOSITE GATE",
        "Risk regime constructive",
        "Source trend improving",
        "Relative strength reclaimed",
        "Re-entry zone confirmed",
        "RSI constructive, not overbought",
        "No tax, wash-sale, account, or settlement block",
        "ARM SIX-GATE MONITOR",
    ):
        assert phrase in source
    assert "gates.some(item => item.state === 'UNAVAILABLE')" in source
    assert "One price boolean cannot satisfy this monitor" in source


def test_analyst_lookthrough_and_resistance_intelligence_are_present():
    source = text(WORKSPACE)
    for phrase in (
        "/api/v2/analyst-detail",
        "/api/v2/portfolio/lookthrough",
        "LOOK-THROUGH",
        "resistanceHoldDays",
        "resistanceHoldStart",
        "resistanceTests",
        "ABOVE",
        "BELOW",
        "TESTING",
        "MA20 / 50 / 200",
        "Relative strength",
    ):
        assert phrase in source


def test_advisory_surface_has_no_broker_execution_path():
    source = text(WORKSPACE)
    forbidden = (
        "submit_order", "place_order", "trade_unlock", "unlock_trade",
        "/api/v2/broker-orders", "/api/v2/broker-proposals", "2fa",
    )
    lowered = source.lower()
    for token in forbidden:
        assert token not in lowered
