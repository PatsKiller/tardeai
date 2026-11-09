from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_exit_workbench_uses_full_fidelity_cache_before_redeploy_fallback():
    workbench = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    hook = read("apps/command-center-v3/src/hooks/useReEntryExitEvidence.ts")
    shared = read("apps/command-center-v3/src/lib/reentrySharedContext.ts")
    # LQ-1663 (2026-11-09): 303128d68 moved the cache-before-fallback read into the shared
    # evidence hook. The full-fidelity cache (portfolio.reentry.exit-universe.v1) is read
    # first and preferred FIELD BY FIELD; the redeploy/journal fallback only fills a gap, and
    # `fullFidelity` says whether the cache answered at all.
    assert "useReEntryExitEvidence" in workbench
    assert "portfolio.reentry.exit-universe.v1" in shared and "EXIT_CACHE_KEY" in hook
    assert "fullFidelity: cacheRows.length > 0" in hook
    assert "mergeRow(preferred, fallback)" in hook
    for token in ("quantity", "price", "proceeds_usd"):
        assert token in hook
    assert "avgExit" in workbench


def test_classification_control_is_in_the_symbol_column_and_opens_a_modal():
    workbench = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    overlay = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    shared = read("apps/command-center-v3/src/lib/reentrySharedContext.ts")
    # LQ-1663 (2026-11-09): the modal moved to ReEntryClassificationOverlay (303128d68); the
    # workbench keeps CLASSIFY in the symbol column and dispatches reentry:classify-symbol.
    assert "classify([summary.symbol])" in workbench
    assert "'CLASSIFY'" in workbench
    assert "role=\"dialog\"" in overlay
    assert "SAVE CLASSIFICATION" in overlay
    assert "CORE HOLDING" in overlay
    for flag in ("growth", "compounding", "dividend", "swing", "short", "defensive", "hedge", "rotation"):
        assert f"'{flag}'" in shared


def test_current_intelligence_is_restored_to_the_primary_page():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    # LQ-1663 (2026-11-09): the page kept every column, under 303128d68's headings; the old
    # free-text labels ("Current status / action", "Last / avg exit", "Portfolio flags", ...)
    # were replaced by named columns and typed states.
    for token in (
        "CURRENT RE-ENTRY INTELLIGENCE",
        "Current decision",
        "Exit evidence",
        "Entry / levels",
        "Valuation / analyst",
        "Evidence audit",
        "RSI",
        "Resistance",
        "Alerts",
        "reentry:classify-symbol",
    ):
        assert token in src


def test_reentry_and_redeploy_use_fixed_surfaces_instead_of_hidden_actions_table():
    reentry = read("apps/command-center-v3/src/pages/ReEntryPageV4.tsx")
    redeploy = read("apps/command-center-v3/src/pages/RedeployDeskIntegrated.tsx")
    for token in ("ReEntryCurrentIntelligence", "ReEntryExitWorkbench"):
        assert token in reentry
        assert token in redeploy
    assert "AuthoritativeExitUniverse" not in reentry
    assert "AuthoritativeExitUniverse" not in redeploy
