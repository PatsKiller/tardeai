from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_exit_summary_has_aggregate_execution_facts_and_bulk_controls():
    src = read("apps/command-center-v3/src/components/reentry/AuthoritativeExitUniverse.tsx")
    for token in (
        "cumulativeShares",
        "averageExitPrice",
        "CUM SHARES",
        "AVG EXIT",
        "BULK CLASSIFY",
        "SELECT VISIBLE",
        "rowShares",
        "rowPrice",
    ):
        assert token.lower() in src.lower()


def test_day_trade_and_scalp_disposition_is_persistent_and_filterable():
    src = read("apps/command-center-v3/src/components/reentry/AuthoritativeExitUniverse.tsx")
    for token in (
        "portfolio.reentry.dispositions.v1",
        "day_trade",
        "momentum_scalp",
        "SUPPRESS FROM RE-ENTRY QUEUE",
        "LONG-TERM QUEUE · HIDE SCALPS",
        "SUPPRESSED ITEMS",
    ):
        assert token in src


def test_operator_guide_explains_manual_and_automatic_rotation_boundaries():
    ui = read("apps/command-center-v3/src/components/reentry/ReEntryHelpGuide.tsx")
    doc = read("docs/features/PORTFOLIO_REENTRY_OPERATOR_GUIDE.md")
    for token in (
        "manual source/destination confirmation",
        "automatic 20-minute advisory monitoring",
        "manual rotation-back order",
    ):
        assert token.lower() in ui.lower()
    assert "The system may suggest a same-account destination" in doc
    assert "The alert never moves money or places an order" in doc
    assert "Missing evidence is `UNAVAILABLE`, never `PASS`" in doc


def test_detailed_analyst_evidence_uses_watch_read_models_and_targets():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryAnalystEvidence.tsx")
    for token in (
        "/api/v2/pro-analyst/pills?map=1",
        "/api/v2/analyst-detail?map=1",
        "UPGRADED",
        "DOWNGRADED",
        "target_mean",
        "target_median",
        "target_high",
        "target_low",
        "Rating distribution unavailable",
        "cannot by itself",
    ):
        assert token.lower() in src.lower()


def test_reentry_and_redeploy_mount_shared_controls_and_help():
    reentry = read("apps/command-center-v3/src/pages/ReEntryPageV4.tsx")
    redeploy = read("apps/command-center-v3/src/pages/RedeployDeskIntegrated.tsx")
    for token in ("ReEntryHelpGuide", "AuthoritativeExitUniverse", "ReEntryAnalystEvidence"):
        assert token in reentry
        assert token in redeploy
